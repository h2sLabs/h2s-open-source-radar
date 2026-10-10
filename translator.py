import re
import unicodedata

import requests

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
UA = "H2S-Open-Source-Radar/0.1"
TRANSLATION_SOURCE = "google+h2s-glossary-v3"

COMMON_PHRASES = [
    ("automatic music transcription", "자동 음악 채보"),
    ("audio-to-midi transcription", "오디오→MIDI 채보"),
    ("audio to midi transcription", "오디오→MIDI 채보"),
    ("music transcription", "음악 채보"),
    ("multi-instrument", "다중 악기"),
    ("agentic workflows", "에이전틱 워크플로"),
    ("collaborative workspace", "협업 워크스페이스"),
    ("mixed song recordings", "혼합된 곡 녹음"),
    ("five-piece school band arrangements", "5인조 스쿨 밴드 편곡"),
    ("pdf scores", "PDF 악보"),
    ("voice design", "보이스 디자인"),
    ("dictation", "받아쓰기"),
    ("speech recognition", "음성 인식"),
    ("midi transcription", "MIDI 채보"),
    ("stem separation", "스템 분리"),
    ("audio separation", "오디오 분리"),
    ("difficulty adjustment", "난이도 조정"),
    ("fully-local", "완전 로컬"),
    ("video dubbing", "영상 더빙"),
    ("audiobook creation", "오디오북 제작"),
    ("print-ready", "인쇄용"),
    ("source separation", "음원 분리"),
    ("singing voice synthesis", "가창 합성"),
    ("speech synthesis", "음성 합성"),
    ("voice conversion", "보이스 변환"),
    ("voice cloning", "보이스 클로닝"),
    ("text-to-speech", "텍스트→음성"),
    ("speech-to-text", "음성→텍스트"),
    ("music generation", "음악 생성"),
    ("music analysis", "음악 분석"),
    ("pitch detection", "음정 감지"),
    ("beat tracking", "비트 추적"),
    ("self-hosted", "자체 호스팅"),
    ("fine-tuning", "파인튜닝"),
    ("real-time", "실시간"),
    ("open-source", "오픈소스"),
    ("open source", "오픈소스"),
    ("inference engine", "추론 엔진"),
    ("deep learning", "딥러닝"),
    ("machine learning", "머신러닝"),
    ("audio plugin", "오디오 플러그인"),
    ("audio plug-in", "오디오 플러그인"),
    ("workflow", "워크플로"),
]

PROTECTED_TERMS = [
    "Audio Unit", "Core ML", "Apple Silicon", "GitHub", "ElevenLabs",
    "MIDI", "DAW", "VST3", "VST", "AU", "CLAP", "LLM", "MCP", "RAG",
    "API", "CLI", "GUI", "SDK", "GPU", "CPU", "CUDA", "Metal", "MLX",
    "LoRA", "TTS", "STT", "ASR", "VAD", "REST", "WebUI", "Python",
    "C++", "JavaScript", "TypeScript", "Swift", "Rust", "PyTorch",
]

POST_REPLACEMENTS = [
    ("오픈 소스", "오픈소스"),
    ("워크 플로", "워크플로"),
    ("파인 튜닝", "파인튜닝"),
    ("줄기 분리", "스템 분리"),
    ("노래하는 목소리 합성", "가창 합성"),
    ("음악 전사", "음악 채보"),
    ("오디오에서 MIDI", "오디오→MIDI"),
    ("오디오 - MIDI", "오디오→MIDI"),
]


def korean_ratio(text):
    text = text or ""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    ko = sum(1 for c in letters if "가" <= c <= "힣")
    return ko / len(letters)


def _boundary_pattern(term):
    escaped = re.escape(term)
    left = r"(?<![A-Za-z0-9])" if term and term[0].isascii() and term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if term and term[-1].isascii() and term[-1].isalnum() else ""
    return left + escaped + right


def _pick_single_language_source(text):
    """Avoid duplicate Korean when GitHub descriptions contain EN+ZH copies."""
    value = (text or "").strip()
    han = [i for i, ch in enumerate(value) if "\u4e00" <= ch <= "\u9fff"]
    if not han:
        return value

    first, last = han[0], han[-1]
    prefix = value[:first].strip(" \t\r\n—-|;/")
    suffix = value[last + 1:].strip(" \t\r\n—-|;/")

    def latin_score(part):
        return sum(1 for ch in part if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))

    if len(prefix) >= 60 and latin_score(prefix) >= 35:
        return prefix
    if len(suffix) >= 60 and latin_score(suffix) >= 35:
        return suffix
    return value


def _placeholderize(text, category=""):
    out = text or ""
    mapping = {}
    counter = 0

    phrases = [
        ("transcription", "전사"),
        ("transcribe", "전사"),
    ] + list(COMMON_PHRASES)
    if category in {
        "작곡·음악 생성", "DAW 자동화", "Audio→MIDI·채보",
        "Stem·오디오 분리", "보컬·가창 합성"
    }:
        phrases = [("arrangement", "편곡")] + phrases

    for src, dst in sorted(phrases, key=lambda x: len(x[0]), reverse=True):
        pattern = _boundary_pattern(src)
        while re.search(pattern, out, flags=re.IGNORECASE):
            token = f"__H2SP{counter}__"
            out = re.sub(pattern, token, out, count=1, flags=re.IGNORECASE)
            mapping[token] = dst
            counter += 1

    for term in sorted(PROTECTED_TERMS, key=len, reverse=True):
        pattern = _boundary_pattern(term)
        while re.search(pattern, out, flags=re.IGNORECASE):
            token = f"__H2ST{counter}__"
            matched = re.search(pattern, out, flags=re.IGNORECASE).group(0)
            out = re.sub(pattern, token, out, count=1, flags=re.IGNORECASE)
            # Preserve canonical capitalization for known engineering terms.
            mapping[token] = term if term.upper() == term or term in {
                "Audio Unit", "Core ML", "Apple Silicon", "GitHub",
                "ElevenLabs", "WebUI", "Python", "JavaScript",
                "TypeScript", "Swift", "Rust", "PyTorch", "Metal"
            } else matched
            counter += 1

    return out, mapping


def _restore(text, mapping):
    out = text
    for token, value in mapping.items():
        # Google normally preserves these verbatim. These variants handle
        # occasional whitespace inserted around underscores/tokens.
        variants = {
            token,
            token.replace("_", " _ "),
            token.replace("__", "__ "),
        }
        for variant in variants:
            out = out.replace(variant, value)
    return out


def _clean(text):
    out = unicodedata.normalize("NFKC", (text or "").strip())
    for src, dst in POST_REPLACEMENTS:
        out = out.replace(src, dst)
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = out.replace("에 대한 오디오 플러그인", "용 오디오 플러그인")
    out = out.replace("귀하의 개인 AI 비서", "개인 AI 어시스턴트")
    out = out.replace("개인 AI 비서", "개인 AI 어시스턴트")
    out = out.replace("난이도 조정를", "난이도 조정을")
    out = out.replace("편곡로", "편곡으로")
    out = out.replace("편곡를", "편곡을")
    return out.strip()


def translate_description(text, category=""):
    """Translate a public GitHub repository description into natural Korean."""
    original = _pick_single_language_source(text)
    if not original:
        return "", "none"
    if korean_ratio(original) >= 0.45:
        return _clean(original), "original-ko"

    prepared, mapping = _placeholderize(original, category)

    response = requests.get(
        TRANSLATE_URL,
        params={
            "client": "gtx",
            "sl": "auto",
            "tl": "ko",
            "dt": "t",
            "q": prepared,
        },
        headers={"User-Agent": UA},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    chunks = payload[0] if isinstance(payload, list) and payload else []
    translated = "".join(
        chunk[0] for chunk in chunks
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str)
    )
    if not translated.strip():
        raise RuntimeError("Translation service returned an empty result")

    translated = _restore(translated, mapping)
    translated = _clean(translated)

    # Category-specific cleanup for terminology that generic translators often
    # mistranslate in music software contexts.
    if category == "Audio→MIDI·채보":
        translated = translated.replace("음악 전사", "음악 채보")
        translated = translated.replace("MIDI 전사", "MIDI 채보")
    return translated, TRANSLATION_SOURCE
