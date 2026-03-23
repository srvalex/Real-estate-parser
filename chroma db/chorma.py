import chromadb

client = chromadb.PersistentClient(path="./my_local_db")

# 2. Create the collection
# We use 'get_or_create' so it doesn't error out if you run this twice
collection = client.get_or_create_collection(name="web_content")