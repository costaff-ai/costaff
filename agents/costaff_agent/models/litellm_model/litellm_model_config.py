import os
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm

# 載入環境變數
load_dotenv()

# 從環境變數取得設定
MODEL_NAME                   = os.getenv("LITELLM_MODEL_NAME")
API_BASE                     = os.getenv("LITELLM_API_BASE")
API_KEY                      = os.getenv("LITELLM_API_KEY")
BOOL_SKIP_SPECIAL_TOKENS     = os.getenv("LITELLM_SKIP_SPECIAL_TOKENS", "False").lower() == "true"

# 初始化 LiteLlm 模型
litellm_model = LiteLlm(
    model=MODEL_NAME,
    api_base=API_BASE,
    api_key=API_KEY,
    extra_body={"skip_special_tokens": BOOL_SKIP_SPECIAL_TOKENS}
)
