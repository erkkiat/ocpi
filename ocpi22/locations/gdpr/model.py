import logging
from transformers import pipeline
from transformers.utils.hub import TRANSFORMERS_CACHE

logger = logging.getLogger(__name__)


class LocationNERModel:
    model_name = "xlm-roberta-large-finetuned-conll03-english"
    _instance = None

    def __new__(cls):
        logger.info(f"Using HF cache dir: {TRANSFORMERS_CACHE}")

        if cls._instance is None:
            cls._instance = super(LocationNERModel, cls).__new__(cls)
            cls._instance.pipeline = None
        return cls._instance

    def load_pipeline(self):
        if self.pipeline is None:
            logger.info("Creating a new pipeline..")
            self.pipeline = pipeline(
                "ner", model=self.model_name, aggregation_strategy="simple"
            )
        else:
            logger.info(f"Using existing pipeline {self.pipeline}")

    def get_entity(self, name: str):
        self.load_pipeline()
        entities = self.pipeline(name)
        inferred_entity = self.infer(entities)
        return inferred_entity

    def infer(self, entities):
        """
        Returns a list containing only the entity with the highest score from a given list of entities.
        If no entities are found, returns an empty list.
        """
        if not entities:
            return []  # No entities found

        # Find the highest scoring entity
        best_entity = max(entities, key=lambda e: float(e["score"]))
        return best_entity["entity_group"]
