# University FAQ - Vector Search

This project implements a semantic search and FAQ system for a University using **Azure CosmosDB (MongoDB vCore)** and **Azure OpenAI**. It uses vector embeddings to understand the semantic meaning of documents and user queries, allowing for highly accurate search results.

## Features

- **DocumentDB Connection**: Connects to Azure CosmosDB for MongoDB.
- **Embeddings Generation**: Uses Azure OpenAI to generate vector embeddings (e.g., `text-embedding-ada-002`) for documents and queries.
- **Vector Search Indexing**: Sets up an `ivf` (Inverted File) vector search index with cosine similarity in CosmosDB.
- **Semantic Search**: Performs vector search queries against the database to find the most relevant FAQ answers based on meaning rather than just keyword matching.

## Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/lucifer230407/university-faq.git
   cd university-faq
   ```

2. **Set up the virtual environment:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the `backend/` directory with the following variables:
   ```env
   AZURE_OPENAI_ENDPOINT="your_azure_openai_endpoint"
   AZURE_OPENAI_API_KEY="your_azure_openai_api_key"
   AZURE_OPENAI_EMBEDDING_DEPLOYMENT="your_embedding_deployment_name"
   MONGO_URI="your_cosmosdb_connection_string"
   ```

## Usage

Run the scripts from the `backend/` directory with the virtual environment activated:

- **Test Database Connection**: `python -m app.testdb`
- **Create Vector Index**: `python -m app.create_vector_index`
- **Check Indexes**: `python -m app.check_vector`
- **Test Embedding Generation**: `python -m app.test_embedding`
- **Insert a Document with Embedding**: `python -m app.insert_embedding`
- **Perform a Vector Search**: `python -m app.vector_search`
