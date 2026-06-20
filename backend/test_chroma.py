from vector_db import get_chroma_client, get_or_create_collection, perform_filtered_search

client = get_chroma_client()
collection = get_or_create_collection(client)

results = perform_filtered_search(
    collection,
    query="recetas de desayuno",
    n_results=100
)

print(f"Total results: {len(results)}")
valid_results = []
for res in results:
    tags = [t.strip().lower() for t in res.get("tags", "").split(",")]
    if "desayuno" in tags:
        valid_results.append(res)

print(f"Valid desayuno results: {len(valid_results)}")
if valid_results:
    print("Example valid:", valid_results[0])
