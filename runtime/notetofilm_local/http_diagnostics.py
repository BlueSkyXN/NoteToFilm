"""只读归类公司 HTTP 错误；区分观察到的错误与尚未证实的根因。"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import socket
import ssl
from urllib.error import URLError


MESSAGES = {
    "authentication": ("接口拒绝了当前身份认证。", "检查本地凭据是否有效，以及认证头格式是否符合公司接口约定。"),
    "permission": ("当前凭据没有执行此请求的权限。", "核对指定模型、分组和通道的访问权限。"),
    "quota": ("接口报告可用额度不足。", "核对该凭据的可用额度及当前计费限制。"),
    "rate_limit": ("接口限制了当前请求频率或并发。", "参考 Retry-After 调整等待或并发，再明确决定是否创建新请求。"),
    "invalid_request": ("接口拒绝了请求参数。", "按错误中的参数名修正字段、取值或输入格式。"),
    "content_rejected": ("接口拒绝了请求中的内容或素材。", "检查服务返回的内容拒绝原因及相关素材。"),
    "model_unavailable": ("接口报告指定模型不可用或不受支持。", "核对精确模型 ID、上游账号类型、凭据权限及该通道的模型映射。"),
    "resource_not_found": ("接口返回资源未找到。", "用请求 ID 核对网关命中渠道、上游路径、部署名和 API Version；仅凭 404 不能确定具体根因。"),
    "unsupported_operation": ("接口报告当前操作或格式不受支持。", "核对当前通道的操作路径、HTTP 方法及请求编码。"),
    "upstream_failure": ("接口返回服务端故障。", "先核查已有任务、结果或用量，确认状态后再决定是否重新提交。"),
    "redirect": ("接口要求跳转，当前请求没有自动跟随。", "核对配置的服务地址与路径，避免向未经确认的地址再次提交。"),
    "request_timeout": ("本次等待超时，尚未取得完整结果。", "生成请求先核查任务、结果或用量；查询或下载可继续已有任务。"),
    "dns_error": ("本机未能解析服务地址。", "检查服务域名、DNS 与代理配置。"),
    "connection_error": ("连接失败或响应传输中断。", "检查网络与代理；生成请求在确认结果前不要重复提交。"),
    "tls_error": ("TLS 连接或证书验证失败。", "检查服务证书及本机代理、证书信任配置，保持证书验证开启。"),
    "invalid_response": ("接口没有返回符合约定的完整响应。", "核对响应格式、请求 ID 与网关记录，保留已有任务标识。"),
    "invalid_media": ("返回的媒体无法按预期格式读取。", "检查响应中的媒体编码与文件；已取得生成结果时优先恢复下载或解码。"),
    "local_io": ("结果已返回，但本地文件处理失败。", "检查输出目录权限、磁盘空间及文件状态，复用已取得的结果。"),
    "local_error": ("本地处理步骤失败。", "检查记录中的异常类型和处理阶段。"),
    "business_error": ("接口返回了业务错误。", "结合错误码、错误消息和请求 ID 核对公司接口约定。"),
    "task_failed": ("远端任务已明确失败。", "保留任务 ID，检查任务返回的失败原因，再决定后续处理。"),
    "http_error": ("接口返回未归类的 HTTP 错误。", "结合状态码、错误正文和请求 ID 核对网关记录。"),
}


def redact_text(value, secrets=(), limit=2000):
    text = str(value)
    for secret in sorted((str(x) for x in secrets if x), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)
    text = re.sub(r"(?i)Bearer\s+[^\s,\"']+", "Bearer [REDACTED]", text)
    text = re.sub(r'''(?ix)(["']?(?:api[-_]?key|authorization|token|password|secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''', r"\1[REDACTED]", text)
    text = re.sub(r"https?://[^\s<>\"']+", "[URL OMITTED]", text)
    text = re.sub(r"[A-Za-z0-9+/=_-]{256,}", "[LONG PAYLOAD OMITTED]", text)
    return text[:limit]


def business_error(body):
    if not isinstance(body, dict):
        return False
    if body.get("error") or body.get("success") is False:
        return True
    # Successful media responses may also carry a numeric status field.
    return body.get("code") not in (None, 0, "0", 200, "200") and bool(body.get("message"))


def _error_fields(body):
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    if isinstance(error, dict):
        fields = {k: error[k] for k in ("code", "type", "message", "param") if error.get(k) is not None}
    else:
        fields = {k: body[k] for k in ("code", "type", "message", "param") if body.get(k) is not None}
        if isinstance(error, str):
            fields.setdefault("message", error)
    return fields


def _nested_error(fields):
    message = fields.get("message")
    if not isinstance(message, str):
        return {}
    # Some New API errors wrap a provider JSON object inside the outer message.
    for match in list(re.finditer(r"\{", message))[:8]:
        try:
            value, _ = json.JSONDecoder().raw_decode(message[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and (value.get("error") or "code" in value):
            found = _error_fields(value)
            if found:
                return found
    return {}


def _retry_after(value):
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0, int(seconds)) if seconds < 10**9 else None
    except (ValueError, TypeError, OverflowError):
        try:
            date = parsedate_to_datetime(str(value))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0, int((date - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None


def diagnose_error(*, status=None, body=None, raw=None, headers=None, method="POST", phase="submit",
                   exception=None, reason=None, secrets=(), accepted_result=False, accepted_task=False):
    """返回脱敏诊断；不会联网、重试，或把候选原因写成已确认根因。"""
    method = method.upper()
    header_map = {str(k).lower(): str(v) for k, v in (headers.items() if headers else [])}
    raw_text = ""
    response_format = "json" if isinstance(body, (dict, list)) else None
    if raw is not None and body is None:
        raw_text = raw[:65536].decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)[:65536]
        try:
            body = json.loads(raw_text)
            response_format = "json"
        except ValueError:
            response_format = "html" if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else "text"
    fields = _error_fields(body)
    nested = _nested_error(fields)
    code = str(nested.get("code", fields.get("code", ""))).lower()
    kind = str(nested.get("type", fields.get("type", ""))).lower()
    message = str(nested.get("message", fields.get("message", ""))).lower()
    provider_status = int(code) if re.fullmatch(r"[45][0-9]{2}", code) else None
    error_status = provider_status or status
    category = None
    root_exception = exception.reason if isinstance(exception, URLError) else exception
    if reason in ("invalid_response", "invalid_media", "local_io", "local_error", "task_failed"):
        category = reason
    elif exception is not None:
        if isinstance(root_exception, ssl.SSLError):
            category = "tls_error"
        elif isinstance(root_exception, socket.gaierror):
            category = "dns_error"
        elif isinstance(root_exception, (TimeoutError, socket.timeout)) or isinstance(root_exception, str) and "timed out" in root_exception.lower():
            category = "request_timeout"
        elif phase == "output_save":
            category = "local_io"
        elif phase == "media_decode":
            category = "invalid_media"
        elif phase in ("response_parse", "response_validate"):
            category = "invalid_response"
        elif isinstance(exception, (URLError, ConnectionError, OSError)):
            category = "connection_error"
        else:
            category = "local_error"
    if category is None:
        signatures = code + " " + kind
        if any(x in signatures for x in ("insufficient_quota", "quota_exceeded", "insufficient_balance", "billing_hard_limit")) or error_status == 402 or any(x in message for x in ("insufficient quota", "insufficient balance", "quota exceeded", "额度不足", "余额不足")):
            category = "quota"
        elif any(x in signatures for x in ("content_policy", "content_filter", "safety_violation", "moderation_blocked")) or any(x in message for x in ("content policy", "content moderation", "内容审核拒绝")):
            category = "content_rejected"
        elif code in ("model_not_found", "model_not_supported", "unsupported_model", "invalid_model") or re.search(
                r"the\s+['\"][^'\"]+['\"]\s+model is not supported when using codex with a chatgpt account", message):
            category = "model_unavailable"
        elif status == 401 or error_status == 401 or code in ("invalid_api_key", "invalid_authentication", "authentication_error"):
            category = "authentication"
        elif status == 403 or error_status == 403 or code in ("permission_denied", "access_denied", "model_access_denied"):
            category = "permission"
        elif error_status == 429 or "rate_limit" in signatures:
            category = "rate_limit"
        elif error_status == 404 or code in ("deploymentnotfound", "resource_not_found", "not_found"):
            category = "resource_not_found"
        elif error_status in (405, 415, 501) or code in ("unsupported_operation", "unsupported_media_type"):
            category = "unsupported_operation"
        elif status in (301, 302, 303, 307, 308):
            category = "redirect"
        elif error_status in (408, 504) or code in ("timeout", "request_timeout", "upstream_timeout"):
            category = "request_timeout"
        elif error_status is not None and error_status >= 500:
            category = "upstream_failure"
        elif error_status in (400, 409, 413, 422) or code in ("invalid_request", "invalid_parameter", "invalid_request_error") or code.startswith("invalidparameter"):
            category = "invalid_request"
        elif business_error(body):
            category = "business_error"
        else:
            category = "http_error" if status and status >= 400 else "invalid_response"
    has_media = isinstance(body, dict) and isinstance(body.get("data"), list) and any(
        isinstance(x, dict) and (x.get("b64_json") or x.get("url")) for x in body["data"])
    if method != "POST":
        outcome = "not_applicable"
    elif accepted_result or has_media:
        outcome = "result_returned"
    elif accepted_task:
        outcome = "task_accepted"
    elif phase == "submit" and isinstance(root_exception, (socket.gaierror, ConnectionRefusedError, ssl.SSLCertVerificationError)):
        outcome = "not_sent"
    elif exception is not None or category == "redirect" or error_status in (408, 504) or (status is not None and status >= 500) or (provider_status is not None and provider_status >= 500):
        outcome = "unknown"
    elif (status is not None and 400 <= status < 500) or business_error(body):
        outcome = "rejected"
    else:
        outcome = "unknown"
    if category in ("dns_error", "connection_error", "tls_error", "request_timeout") and exception is not None:
        layer = "transport"
    elif category in ("invalid_response", "invalid_media", "local_io", "local_error"):
        layer = "local_processing" if category in ("local_io", "local_error") else "response_validation"
    elif "upstream" in str(fields.get("type", "")).lower() or "upstream" in str(fields.get("code", "")).lower():
        layer = "upstream_reported_by_gateway"
    else:
        layer = "unknown"
    summary, action = MESSAGES[category]
    if outcome == "unknown" and method == "POST":
        action += " 提交结果尚未确认，先核查已有任务或用量，不自动重发。"
    policy = ("resume_existing_task" if method != "POST" and category in ("rate_limit", "upstream_failure", "connection_error", "request_timeout")
              else "recover_existing_result" if outcome == "result_returned"
              else "inspect_existing_task" if outcome == "task_accepted"
              else "verify_before_resubmit" if outcome == "unknown"
              else "fix_before_new_attempt")
    result = {"category": category, "summary": summary, "next_action": action,
              "http_status": status, "method": method, "phase": phase, "reported_layer": layer,
              "submission_outcome": outcome, "retry_policy": policy, "automatic_retry": False,
              "root_cause_confirmed": False}
    request_id = header_map.get("x-request-id") or header_map.get("x-oneapi-request-id")
    if not request_id and isinstance(body, dict):
        request_id = body.get("request_id")
    if request_id:
        result["request_id"] = redact_text(request_id, secrets, 300)
    if fields:
        result["error"] = {k: redact_text(v, secrets) for k, v in fields.items()}
    if nested:
        result["nested_error"] = {k: redact_text(v, secrets) for k, v in nested.items()}
    if code == "deploymentnotfound":
        result["reported_resource"] = "deployment"
    if provider_status is not None:
        result["reported_error_status"] = provider_status
    if response_format:
        result["response_format"] = response_format
    if raw_text and response_format != "json":
        result["body_excerpt"] = redact_text(raw_text, secrets)
    if exception is not None:
        result["exception_type"] = type(exception).__name__
        if root_exception is not exception and isinstance(root_exception, BaseException):
            result["cause_type"] = type(root_exception).__name__
    allowed = ("content-type", "server", "date", "x-request-id", "x-oneapi-request-id", "retry-after", "traceparent")
    selected_headers = {k: redact_text(header_map[k], secrets, 300) for k in allowed if k in header_map}
    if selected_headers:
        result["response_headers"] = selected_headers
    retry_after = _retry_after(header_map.get("retry-after"))
    if retry_after is not None:
        result["retry_after_seconds"] = retry_after
    return result
