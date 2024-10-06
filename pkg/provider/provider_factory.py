from .acgn_ttson import ACGNTTSon
from .gpt_sovits import GPTSovits
from .doubao_tts import DoubaoTTS


class ProviderFactory:
    @staticmethod
    def get_provider(provider_name, config, temp_dir_path):
        if provider_name == "acgn_ttson":
            provider = ACGNTTSon(temp_dir_path)
            provider.set_token(config["token"])
            return provider
        elif provider_name == "gpt_sovits":
            return GPTSovits(config["url"], temp_dir_path)
        elif provider_name == "doubao_tts":
            provider = DoubaoTTS(config["url"], temp_dir_path)
            provider.init_config(config["token"], config["appid"], config["cluster"], config["voice_type"], config["api_url"], config["encoding"])
            return provider
        else:
            raise ValueError(f"未知的TTS平台: {provider_name}")
