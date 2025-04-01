from collections import defaultdict

from transformers import pipeline, XLMRobertaTokenizer

from ocpi22.models.location import Location
import json


def infer(entities):
    """
    Returns the entity group with the highest score from a given list of entities as a string.
    If no entities are found, returns an empty list.
    """
    if not entities:
        return []  # No entities found

    # Find the highest scoring entity
    best_entity = max(entities, key=lambda e: float(e["score"]))
    return best_entity["entity_group"]


def check_names():
    model_name = "xlm-roberta-large-finetuned-conll03-english"
    ner_pipeline = pipeline("ner", model=model_name, aggregation_strategy="simple")

    print("model setup completed.. !!")

    locations = Location.objects.all()

    print(f"{locations.count()} locations fetched")

    location_name_and_uids = defaultdict(list)
    for location in locations:
        location_name_and_uids[location.name].append(location.uid)
    duplicate_name_and_uids = {
        name: uids for name, uids in location_name_and_uids.items()
    }
    print("Adding our tokens and resizing the model")

    tokenizer = XLMRobertaTokenizer.from_pretrained(model_name)
    tokenizer.add_tokens(list(duplicate_name_and_uids.keys()))

    # Avoid resizing unnecessarily - only resize if the tokenizer has been updated
    ner_pipeline.model.resize_token_embeddings(len(tokenizer))

    print("Setting up token and resizing completed")

    print(f"Processing {len(duplicate_name_and_uids)} unique locations")

    count = 0
    result = []
    for name, uids in duplicate_name_and_uids.items():
        entities = ner_pipeline(name)
        custom_entities = [
            {"entity": entity["entity_group"], "score": str(entity["score"])}
            for entity in entities
        ]
        inferred = infer(entities)
        result.append({"uids": uids, "entities": custom_entities, "inferred": inferred})
        count += 1
        if inferred != "PER":
            print(f"'{name}' inferred as {inferred}")
        else:
            update_database(uids)

    data = json.dumps(result)

    print("Writing to file")

    with open("output.json", "w") as f:
        f.write(data)

    print("Writing to file completed...!!")


def update_database(uids: list):
    for uid in uids:
        location = Location.objects.get(uid=uid)
        location.name = location.address
        location.save()
        print(f"Updating name for Location UID:{uid} as {location.address}")
