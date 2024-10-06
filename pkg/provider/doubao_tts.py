# coding=utf-8

import asyncio
import aiohttp
import websockets
import uuid
import json
import gzip
import copy
import os
import time
from aiohttp import ClientSession, ClientTimeout
from aiohttp_retry import RetryClient, ExponentialRetry
from graiax import silkcoder
from .base_provider import TTSInterface

MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0", 2: "last message from server (seq < 0)", 3: "sequence number < 0"}
MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

class DoubaoTTS(TTSInterface):
    def __init__(self, default_url: str, temp_dir_path: str):
        self.default_url = default_url
        self.temp_dir_path = temp_dir_path
        
    def init_config(self, token: str, appid: str, cluster: str, voice_type: str, api_url: str, encoding: str):
        self.token = token
        self.appid = appid
        self.cluster = cluster
        self.voice_type = voice_type
        self.api_url = api_url
        self.encoding = encoding
        
    async def get_character_list(self, file_path: str = None):
        # 假设字符列表是固定的，可以从文件或硬编码中获取
        character_list = [
            {"id": 1, "name": "Xavier"},
            {"id": 2, "name": "Sylus"},
            {"id": 3, "name": "Rafayel"}
        ]
        if file_path:
            with open(file_path, 'w') as f:
                json.dump(character_list, f)
        return character_list
    
    async def generate_audio_http(self, text: str, character_name: str, **kwargs):
        emotion = kwargs.get('emotion', 'default')
        batch_size = kwargs.get('batch_size', 1)
        speed = kwargs.get('speed', 1.0)
        save_temp = kwargs.get('save_temp', True)

        request_json = {
            "app": {
                "appid": self.appid,
                "token": self.token,
                "cluster": self.cluster
            },
            "user": {
                "uid": "uid123"
            },
            "audio": {
                "voice_type": self.voice_type,
                "encoding": self.encoding,
                "compression_rate": 1,
                "rate": 24000,
                "speed_ratio": speed,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
                "emotion": emotion,
                "language": "cn"
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "silence_duration": "125",
                "with_frontend": "1",
                "frontend_type": "unitTson",
                "pure_english_opt": "1"
            }
        }
        
        # 打印请求数据以便调试
        print("Request JSON:", json.dumps(request_json, indent=4))

        payload_bytes = str.encode(json.dumps(request_json))
        payload_bytes = gzip.compress(payload_bytes)
        full_client_request = bytearray(b'\x11\x10\x11\x00')
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/octet-stream"
        }
        retry_options = ExponentialRetry(attempts=3)
        timeout = ClientTimeout(total=30)
        
        try:
            async with RetryClient(aiohttp.ClientSession(), retry_options=retry_options, timeout=timeout) as session:
                async with session.post(self.api_url, headers=headers, data=full_client_request) as response:
                    if response.status == 200:
                        file_name = f"character_{character_name}_{emotion}_{int(time.time())}.wav"
                        save_path = os.path.join(self.temp_dir_path, file_name)
                        with open(save_path, "wb") as file_to_save:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                file_to_save.write(chunk)

                        # Convert to silk format
                        silk_path = self._convert_to_silk(save_path)
                        return silk_path
                    else:
                        error_text = await response.text()
                        print(f"Error generating audio: {response.status}")
                        return None
                    
        except Exception as e:
            print(f"Error generating audio: {str(e)}")
            return None
                
    async def generate_audio(self, text: str, character_name: str, **kwargs):
        emotion = kwargs.get('emotion', 'default')
        batch_size = kwargs.get('batch_size', 1)
        speed = kwargs.get('speed', 1.0)
        save_temp = kwargs.get('save_temp', True)

        request_json = {
            "app": {
                "appid": self.appid,
                "token": self.token,
                "cluster": self.cluster
            },
            "user": {
                "uid": "uid123"
            },
            "audio": {
                "voice_type": self.voice_type,
                "encoding": self.encoding,
                "speed_ratio": speed,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "submit"
            }
        }

        payload_bytes = str.encode(json.dumps(request_json))
        payload_bytes = gzip.compress(payload_bytes)
        full_client_request = bytearray(b'\x11\x10\x11\x00')
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        header = {"Authorization": f"Bearer; {self.token}"}
        async with websockets.connect(self.api_url, extra_headers=header, ping_interval=None) as ws:
            await ws.send(full_client_request)
            file_name = f"character_{character_name}_{emotion}_{int(time.time())}.wav"
            save_path = os.path.join(self.temp_dir_path, file_name)
            with open(save_path, "wb") as file_to_save:
                while True:
                    res = await ws.recv()
                    done = self.parse_response(res, file_to_save)
                    if done:
                        break

        # Convert to silk format
        silk_path = self._convert_to_silk(save_path)
        return silk_path

    def parse_response(self, res, file):
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size*4]
        payload = res[header_size*4:]

        if message_type == 0xb:  # audio-only server response
            if message_type_specific_flags == 0:  # no sequence number as ACK
                return False
            else:
                sequence_number = int.from_bytes(payload[:4], "big", signed=True)
                payload_size = int.from_bytes(payload[4:8], "big", signed=False)
                payload = payload[8:]
                file.write(payload)
                if sequence_number < 0:
                    return True
                else:
                    return False
        elif message_type == 0xf:
            code = int.from_bytes(payload[:4], "big", signed=False)
            msg_size = int.from_bytes(payload[4:8], "big", signed=False)
            error_msg = payload[8:]
            if message_compression == 1:
                error_msg = gzip.decompress(error_msg)
            error_msg = str(error_msg, "utf-8")
            print(f"Error message: {error_msg}")
            return True
        elif message_type == 0xc:
            msg_size = int.from_bytes(payload[:4], "big", signed=False)
            payload = payload[4:]
            if message_compression == 1:
                payload = gzip.decompress(payload)
            print(f"Frontend message: {payload}")
        else:
            print("undefined message type!")
            return True

    def _convert_to_silk(self, audio_path: str) -> str:
        silk_path = audio_path.replace(".wav", ".silk")
        silkcoder.encode(audio_path, silk_path)
        return silk_path
    
    async def _download_audio(self, url, save_path):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(save_path, "wb") as f:
                            f.write(await response.read())
                        return True
                    else:
                        print(f"Error downloading audio: {response.status}")
                        return False
        except Exception as e:
            print(f"Error downloading audio: {str(e)}")
            return False

if __name__ == '__main__':
    doubao_tts = DoubaoTTS(default_url="your_default_url", temp_dir_path="/path/to/temp/dir")
    loop = asyncio.get_event_loop()
    character_list = loop.run_until_complete(doubao_tts.get_character_list())
    print(f"Character list: {character_list}")
    output_path = loop.run_until_complete(doubao_tts.generate_audio("测试文本", 1))
    print(f"Audio saved to: {output_path}")