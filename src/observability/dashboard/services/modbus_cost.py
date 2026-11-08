"""Explicit, dated public-price estimates; never a bill or automatic price discovery."""
from urllib.parse import urlsplit

SOURCE = "https://help.aliyun.cn/zh/model-studio/qwen3-7-flash"


def estimate_calls(model, endpoint, records):
    if urlsplit(endpoint or "").hostname != "dashscope.aliyuncs.com" or model not in {"qwen3.7-flash", "qwen3.7-flash-2026-07-15"}:
        return {"amount": None, "status": "unsupported_price_profile"}
    cost = 0.0
    for record in records:
        usage = record.get("usage", {})
        if record.get("failed") or any(not isinstance(usage.get(k), int) or isinstance(usage.get(k), bool) or usage[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
            return {"amount": None, "status": "incomplete_usage"}
        incoming = usage["prompt_tokens"]
        rate_in, rate_out = (0.2, 0.8) if incoming <= 32768 else (0.6, 2.4) if incoming <= 262144 else (1.2, 4.8)
        cost += (incoming * rate_in + usage["completion_tokens"] * rate_out) / 1_000_000
    return {"amount": round(cost, 8), "currency": "CNY", "status": "public_list_price_estimate",
            "verified_on": "2026-11-07", "source": SOURCE,
            "assumptions": "北京区域实时文本公开价，按每次请求输入档位；未计缓存折扣、优惠、免费额度与账单调整。非实际扣款。"}
