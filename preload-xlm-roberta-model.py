import os
from logging import getLogger

from transformers import AutoTokenizer, AutoModel

logger = getLogger(__name__)

MODEL_NAME = os.getenv(
    "XLM-MODEL", "xlm-roberta-large-finetuned-conll03-english"
)  # Replace with your model namea

logger.info(f"Preloading Hugging Face model: {MODEL_NAME}")
AutoTokenizer.from_pretrained(MODEL_NAME)
AutoModel.from_pretrained(MODEL_NAME)
logger.info("Model downloaded and cached.")
