from dotenv import load_dotenv
from firebase_admin import initialize_app
from firebase_functions import https_fn, options
from huggingface_hub import InferenceClient
import json
import os
from pinecone import Pinecone
from pymongo import MongoClient


load_dotenv()
initialize_app()


class KTPaul:

    def __init__(
        self,
        huggingface_token: str = os.environ["huggingface_token"],
        pinecone_api_key: str = os.environ["pinecone_api_key"],
        pinecone_host: str = os.environ["pinecone_host"],
        history: list = None,
    ):

        self.pc = Pinecone(api_key=pinecone_api_key)
        self.embedding_model = "multilingual-e5-large"
        self.index = self.pc.Index(host=pinecone_host)
        self.chat_client = InferenceClient(
            token=huggingface_token, model="meta-llama/Meta-Llama-3-8B-Instruct"
        )
        self.history = history[-10:] if history else []

    def retrieve_context(self, query: str, top_k: int = 3) -> str:

        query_embedding = self.pc.inference.embed(
            model=self.embedding_model,
            inputs=[query],
            parameters={"input_type": "query"},
        )

        results = self.index.query(
            vector=query_embedding[0].values,
            top_k=top_k,
        )

        context_document_ids = [i["id"] for i in results["matches"]]
        try:
            with MongoClient(host=os.environ["assistant_mongoDBURL"]) as mongo_client:
                database = mongo_client["assistant"]
                rag_documents = database["rag_documents"]
                context_documents = rag_documents.find(
                    {"name": {"$in": context_document_ids}}
                )
                context = ""
                for c in context_documents:
                    context += f'\n{c["text"]}\n'
        except Exception as e:
            print(f"Failed to retrieve contextual documents from MongoDB: {e}")

        return context

    def generate_response(self, query: str, context: str) -> str:

        enhanced_query = f"""Only answer the query as related to Kappa Theta Pi (KTP), the professional technology fraternity. No need to cite the context.\nQUERY:\n {query}\n\nCONTEXT:\n {context}"""

        self.history.append({"role": "user", "content": enhanced_query})

        response = self.chat_client.chat_completion(self.history, max_tokens=250)

        self.history.append(
            {
                "role": "assistant",
                "content": response.choices[0].message.content,
            }
        )

        return response.choices[0].message.content

    def query_chatbot(self, query: str) -> str:

        context = self.retrieve_context(query=query)
        response = self.generate_response(query=query, context=context)

        return response


@https_fn.on_request(
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["get", "post"],
    )
)
def firebase_handler(req: https_fn.Request) -> https_fn.Response:

    query = req.args.get("query")
    if query is None:
        return https_fn.Response("No query parameter provided", status=400)

    chatbot = KTPaul(history=req.args.get("history", []))
    response = chatbot.query_chatbot(query=query)

    return https_fn.Response(
        json.dumps({"response": response, "history": chatbot.history}),
        content_type="application/json",
        status=200,
    )


if __name__ == "__main__":

    chatbot = KTPaul()
    query = input("\nHi, I'm KTPaul! How can I help you?\n\n")

    while True:
        response = chatbot.query_chatbot(query=query)
        print(response)
        query = input("\n")