from  config.settings import get_settings
_s = get_settings()

def get_llm(temperature: float | None = None, json_mode: bool = False):
    temp = temperature if temperature is not None else _s.llm_temperature
    if _s.llm_provider == "openai":
        return _get_openai_llm(temp, json_mode)
    elif _s.llm_provider == "ollama":
        return _get_ollama_llm(temp, json_mode)

def _get_openai_llm(temperature, json_mode):
    from langchain_openai import ChatOpenAI
    kwargs = dict(model=_s.openai_model, temperature=temperature, api_key=_s.openai_api_key)
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)

def _get_ollama_llm(temperature, json_mode):
    from langchain_ollama import ChatOllama
    kwargs = dict(model=_s.ollama_model, base_url=_s.ollama_base_url, temperature=temperature)
    if json_mode:
        kwargs["format"] = "json"   # Ollama native JSON enforcement
    return ChatOllama(**kwargs)