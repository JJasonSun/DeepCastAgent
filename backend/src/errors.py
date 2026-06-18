"""DeepCast 统一异常层级。"""


class DeepCastError(Exception):
    """所有 DeepCast 业务异常的基类。"""


class SearchError(DeepCastError):
    """搜索服务异常。"""


class ReportError(DeepCastError):
    """报告生成异常。"""


class ScriptError(DeepCastError):
    """脚本生成异常。"""


class TTSError(DeepCastError):
    """TTS 语音合成异常。"""


class AudioSynthesisError(DeepCastError):
    """音频拼接异常。"""
