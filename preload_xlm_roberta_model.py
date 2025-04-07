import os
from logging import getLogger

from transformers import XLMRobertaTokenizer

logger = getLogger(__name__)

MODEL_NAME = os.getenv("XLM-MODEL", "xlm-roberta-large-finetuned-conll03-english")

logger.info(f"Preloading Hugging Face model: {MODEL_NAME}")
XLMRobertaTokenizer.from_pretrained(MODEL_NAME)
logger.info("Model downloaded and cached.")
