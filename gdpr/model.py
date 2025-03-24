from transformers import pipeline, XLMRobertaTokenizer


class LocationNERModel:
    model_name = "xlm-roberta-large-finetuned-conll03-english"
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LocationNERModel()
        return cls._instance

    def __init__(self):
        self.pipeline = pipeline(
            "ner", model=self.model_name, aggregation_strategy="simple"
        )
        self.tokenizer = XLMRobertaTokenizer.from_pretrained(self.model_name)

    def get_entity(self, name: str):
        # This step directs the model not to divide the location name into subtokens
        self.tokenizer.add_tokens(name)

        # After adding new tokens and increasing the vocabulary this step updates the model.
        self.pipeline.model.resize_token_embeddings(len(self.tokenizer))

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
