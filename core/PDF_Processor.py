import json
import re
import traceback
import aiohttp
from dotenv import load_dotenv
import openai
from termcolor import colored
import io
from PIL import Image
import os
import logging
import uuid
import fitz  # PyMuPDF
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
import requests
import hashlib
import aiofiles
from azure.storage.blob import BlobServiceClient
from azure.storage.blob.aio import BlobClient
from utility.decorators import time_it
import asyncio
import cv2
import numpy as np
from PIL import Image
import pytesseract 
import pymupdf4llm


load_dotenv()

# Azure Cognitive Search configurations
SEARCH_ENDPOINT = os.getenv("SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("SEARCH_KEY")
SEARCH_INDEX_NAME = os.getenv("SEARCH_INDEX_NAME")

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
connection_string = os.getenv("BLOB_CONNECTION_STRING")
container_name = os.getenv("CONTAINER_NAME")
blob_access_key = os.getenv("BLOB_ACCESS_KEY")


class DocumentProcessor:
    def __init__(self, user_email):
        self.search_client = SearchClient(
            endpoint=SEARCH_ENDPOINT, 
            index_name=SEARCH_INDEX_NAME,
            credential=AzureKeyCredential(SEARCH_KEY)
        )
        self.search_service_name = "bibotsearch"
        self.index_name = SEARCH_INDEX_NAME
        self.api_key = SEARCH_KEY
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_name = container_name
        self.blob_access_key = blob_access_key
        self.user_email = user_email

        self.llm = openai.AsyncAzureOpenAI(
            api_key=AZURE_OPENAI_KEY,  
            api_version="2023-03-15-preview",
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        print("Azure Search and OpenAI connections initialized")
        
        # Set up pytesseract path if needed (uncomment and configure if necessary)
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Windows
        # For Linux/Mac, ensure Tesseract is installed and in PATH
        

    @time_it
    async def store_in_azure_blob(self, content, doc_type, file_hash):
        print("Storing Docs chunks in Blob...")
        try:
            doc_chunk_id = f"{doc_type}-{file_hash}-{uuid.uuid4()}"
            container_client = self.blob_service_client.get_container_client(self.container_name)
            if not container_client.exists():
                print(f"Container '{self.container_name}' does not exist. Creating container...")
                await container_client.create_container()

            print("Calling get blob client...")
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=doc_chunk_id
            )
            print("Uploading blob content...")
            blob_client.upload_blob(content)
            blob_url = blob_client.url
            print(f"Stored document chunk as blob: {blob_url}")
            return blob_url

        except Exception as e:
            print(f"Error storing document chunk in Blob Storage: {e}")
            return None

    @time_it
    async def generate_file_hash(self, file):
        """Generates a unique hash based on the file's metadata instead of its content."""
        hasher = hashlib.sha256()
        
        normalized_path = os.path.abspath(file)
        file_stat = os.stat(normalized_path)
        
        print(normalized_path)
        metadata = (normalized_path, file_stat.st_size)
        
        for item in metadata:
            hasher.update(str(item).encode('utf-8'))
        
        return hasher.hexdigest()

    @time_it
    async def chat_completion_request(self, model, messages, tools=None, response_format=None):
        if tools is not None:
            tool_choice = "auto"
        else:
            tool_choice = None

        if response_format is True:
            response_format = {"type": "json_object"}
        else:
            response_format = None

        response = await self.llm.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format
        )
        return response

    @time_it
    async def save_pdf(self, pdf, filename):
        try:
            local_directory = "./saved_pdfs"
            if not os.path.exists(local_directory):
                os.makedirs(local_directory)
            local_file_path = os.path.join(local_directory, filename)

            with open(local_file_path, "wb") as local_file:
                local_file.write(pdf)

            print(f"PDF saved locally at {local_file_path} as {filename}")
            return local_file_path

        except Exception as e:
            print(f"Error saving PDF: {e}")
            return None
    
    @time_it
    async def check_existing_embedding(self, file_hash, user_id):
        """Asynchronously checks if the embedding for a given file hash already exists in Azure Search."""
        try:
            search_url = f"https://{self.search_service_name}.search.windows.net/indexes/{self.index_name}/docs/search?api-version=2023-07-01-Preview"
            headers = {"Content-Type": "application/json", "api-key": self.api_key}
    
            body = {
                "search": "*",
                "select": "id",
                "filter": f"file_hash eq '{file_hash}' and user eq '{user_id}'"
            }
    
            print("Making an async API call to check existing file...")

            async with aiohttp.ClientSession() as session:
                async with session.post(search_url, headers=headers, json=body) as response:
                    print(f"Status Code: {response.status}")
                    response.raise_for_status()
                    response_text = await response.text()
                    print(f"Response Text: {response_text}")
                    search_results = await response.json()
    
                    if search_results.get("value"):
                        return True 
    
            return False 
    
        except Exception as e:
            print(f"Error checking existing embeddings: {e}")
            return False

    @time_it
    async def is_scanned_pdf(self, pdf_path):
        """Determine if a PDF is primarily scanned images rather than digital text."""
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            image_pages = 0
            text_content = ""
            
            # Check the first few pages (or all if less than 5)
            pages_to_check = min(5, total_pages)
            
            for page_num in range(pages_to_check):
                page = doc[page_num]
                text = page.get_text()
                text_content += text
                
                # If page has very little text but has images, likely a scanned page
                if len(text.strip()) < 100:
                    images = page.get_images(full=True)
                    if len(images) > 0:
                        image_pages += 1
            
            doc.close()
            
            # If more than 50% of checked pages are image-based with little text
            is_scanned = (image_pages / pages_to_check) > 0.5 or len(text_content.strip()) < 200
            print(f"PDF scan detection: {is_scanned} (Image pages: {image_pages}/{pages_to_check})")
            return is_scanned
            
        except Exception as e:
            print(f"Error detecting if PDF is scanned: {e}")
            return False

    @time_it
    async def extract_text_with_ocr(self, pdf_path):
        """Extract text from scanned PDF pages using OCR."""
        try:
            print("Starting OCR processing...")
            doc = fitz.open(pdf_path)
            extracted_texts = []
            image_dir = "./temp_images"
            os.makedirs(image_dir, exist_ok=True)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # 300 DPI rendering
                
                img_path = os.path.join(image_dir, f"page_{page_num}.png")
                pix.save(img_path)
                
                # Process the image with OpenCV for better OCR results
                img = cv2.imread(img_path)
                if img is None:
                    print(f"Failed to load image for page {page_num}")
                    continue
                    
                # Preprocess image for better OCR
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
                )
                
                # OCR with pytesseract
                custom_config = r'--oem 3 --psm 6'
                text = pytesseract.image_to_string(gray, config=custom_config)
                
                # Clean up the extracted text
                text = text.strip()
                if text:
                    extracted_texts.append({
                        "page": page_num + 1,
                        "text": text
                    })
                    
                # Clean up temporary image file
                os.remove(img_path)
                
            doc.close()
            
            # Clean up empty temp directory
            try:
                os.rmdir(image_dir)
            except:
                pass
                
            return extracted_texts
            
        except Exception as e:
            print(f"Error extracting text with OCR: {e}")
            traceback.print_exc()
            return []

    @time_it
    async def process_pdf_and_summarize(self, pdf_path, filename):
        print("Processing PDF started...")
        total_tokens_used = 0
        summaries = []
        text_id_counter = 0
        output_dir = "./output_csvs"
        os.makedirs(output_dir, exist_ok=True)

        try:
            async with aiofiles.open(pdf_path, "rb") as f:
                pdf_data = await f.read()

            if len(pdf_data) == 0:
                print("The PDF file is empty.")
                return 0, None

            saved_file_path = await self.save_pdf(pdf_data, filename)
            if not saved_file_path or os.path.getsize(saved_file_path) == 0:
                print("Failed to save PDF, aborting processing.")
                return 0, None

            file_hash = await self.generate_file_hash(saved_file_path)
            if await self.check_existing_embedding(file_hash, self.user_email):
                print(f"Embeddings for {filename} already exist. Skipping.")
                return 0, file_hash

            # Detect if PDF is scanned
            is_scanned = await self.is_scanned_pdf(saved_file_path)
            
            if is_scanned:
                print("Detected scanned PDF. Proceeding with OCR processing...")
                ocr_results = await self.extract_text_with_ocr(saved_file_path)
                
                if not ocr_results:
                    print("OCR processing failed or returned no text.")
                    return 0, None
                
                # Process OCR results by pages or chunks
                for result in ocr_results:
                    page_num = result["page"]
                    clean_text = result["text"].strip()
                    
                    if not clean_text or len(clean_text) < 30:
                        print(f"Skipping page {page_num} due to insufficient text.")
                        continue
                    
                    text_summary = clean_text
                    
                    embedding = await self.generate_embedding(text_summary)
                    if not embedding:
                        print(f"Embedding generation failed for page {page_num}. Skipping storage.")
                        continue
                    
                    text_id = f"text-{uuid.uuid4()}"
                    blob_url = await self.store_in_azure_blob(clean_text, 'text', file_hash)
                    
                    self.store_in_azure_search(
                        embedding, 
                        text_summary, 
                        {
                            'type': 'text',
                            'hash': file_hash,
                            'user': self.user_email,
                            'id': text_id,
                            'page': page_num
                        },
                        file_hash,
                        filename, 
                        blob_url
                    )
                    summaries.append(text_summary)
                    text_id_counter += 1
                
                print(f"Processed {text_id_counter} pages from scanned PDF.")
                
            else:
                print("Processing digital PDF using pyMuPDF4LLM...")
                llama_reader = pymupdf4llm.LlamaMarkdownReader()
                llama_docs = llama_reader.load_data(saved_file_path)
                print(f"Extracted {len(llama_docs)} document nodes.")
    
                for node in llama_docs:
                    # Assuming each node has an attribute 'text' that holds the markdown content
                    clean_text = node.text.strip() if hasattr(node, "text") else str(node).strip()
                    # print(colored(f"Cleansed Text: {clean_text}", "green"))
                    if not clean_text or len(clean_text) < 30:
                        print("Skipping node due to insufficient text.")
                        continue
                    
                    text_summary = clean_text
    
                    # try:
                    #     text_summary, tokens = await self.generate_summary(clean_text)
                    # except Exception as e:
                    #     if "content_filter" in str(e).lower():
                    #         print("Content filter triggered. Skipping this node.")
                    #         continue
                    #     else:
                    #         raise e
    
                    # if not text_summary:
                    #     print("Summary is empty or None. Skipping embedding.")
                    #     continue
    
                    embedding = await self.generate_embedding(text_summary)
                    if not embedding:
                        print("Embedding generation failed or returned None. Skipping storage.")
                        continue
    
                    text_id = f"text-{uuid.uuid4()}"
                    blob_url = await self.store_in_azure_blob(clean_text, 'text', file_hash)
                    # print(colored(f"Text Summary: {text_summary}", "yellow"))
                    self.store_in_azure_search(
                        embedding, 
                        text_summary, 
                        {
                            'type': 'text',
                            'hash': file_hash,
                            'user': self.user_email,
                            'id': text_id
                        },
                        file_hash,
                        filename, 
                        blob_url
                    )
                    summaries.append(text_summary)
                    # total_tokens_used += tokens
                    text_id_counter += 1
    
                print(f"Processed {text_id_counter} document nodes from PDF.")

            return 0, file_hash

        except Exception as e:
            error_details = traceback.format_exc()
            print(f"Error processing PDF: {error_details}")
            return 0, None


    @time_it
    async def generate_summary(self, text):
        print("Getting Summaries...")
        try:
            response = await self.chat_completion_request(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an assistant that summarizes text. Return the summary in JSON format."},
                    {"role": "user", "content": f"Summarize the following text: {text}"}
                ],
                response_format=True  
            )

            summary = response.model_dump()['choices'][0]['message']['content']
            tokens_used = response.usage.total_tokens
            return summary, tokens_used
        except Exception as e:
            print(f"Error generating summary: {e}")
            return None, 0

    @time_it
    async def generate_embedding(self, text):
        print("Generating the embeddings...")
        try:
            embedding = await self.llm.embeddings.create(
                model="text-embedding-3-small", input=text
            )
            return embedding.data[0].embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None

    @time_it
    def store_in_azure_search(self, embedding, summary, metadata, file_hash, file_name, blob_url):
        print("Storing in Azure AI Search...")
        try:
            doc_id = str(uuid.uuid4())
            doc = {
                "id": doc_id,
                "embedding": embedding,
                "summary": summary,
                "metadata": json.dumps(metadata),
                "file_hash": file_hash,
                "file_name" : file_name,
                "user": self.user_email,
                "blob_url": blob_url
            }

            print("Calling upload_documents function in Azure Search...")
            self.search_client.upload_documents(documents=[doc])
            print(f"Document with id {doc_id} stored successfully in Azure AI Search.")

        except Exception as e:
            print(f"Error storing in Azure AI Search: {e}")

    @time_it
    def search_similar_documents(self, query_embedding, file_hash, file_name, top_k=5):
        print("Searching for relevant documents in Azure AI Search...")
        search_url = f"https://{self.search_service_name}.search.windows.net/indexes/{self.index_name}/docs/search?api-version=2023-07-01-Preview"
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key
        }
        body = {
            "search": "*",
            "vector": {
                "value": query_embedding,
                "fields": "embedding",
            },
            "top": top_k,
            "filter": f"file_name eq '{file_name}' and user eq '{self.user_email}'"
        }

        try:
            with requests.post(search_url, headers=headers, json=body, timeout=60) as response:
                response.raise_for_status()
                search_results = response.json()
                relevant_docs = []
                for result in search_results.get("value", []):
                    # doc = {
                    #     "summary": result.get("summary")
                    #     # "blob_url": result.get("blob_url")
                    # }
                    relevant_docs.append(result.get("summary"))

                return relevant_docs

        except requests.exceptions.HTTPError as err:
            print(f"Error querying Azure AI Search: {err}")
            print("Response content:", response.text)
            return []

    @time_it
    async def generate_llm_response(self, user_query, combined_texts, conversational_history):
        try:
            base_prompt=[
                    {
                        "role": "system", 
                        "content": (
                            f"You are an advanced AI system tasked with synthesizing information"
                            f"from complex PDF documents that may include text, tables or image summaries\n"
                            f"Your goal is to generate concise, human-readable responses that clearly answer user questions.\n"
                            f"Keep the data points and values intact, and avoid introducing new information or unnecessary new lines or characters.\n"
                            f"Respond in JSON format.\n"
                        )
                    },
                    {"role": "user", "content": f"Answer the question based only on the following context, which can include text, tables or image summaries(given in markdown):\n {combined_texts} and Question: {user_query}"}
                ]
            
            if conversational_history:
                base_prompt.extend(conversational_history)
            
            response = await self.chat_completion_request(
                model="gpt-4o-mini",
                messages=base_prompt,
                response_format=True
            )
            return response

        except Exception as e:
            print(f"Error generating LLM response: {e}")
            return "Failed to generate a summary."

    @time_it
    async def synthesize_responses(self, user_query, search_results, conversational_history):
        print("Synthesizing Response...")
        try:
            # combined_texts = ""
            # for result in search_results:
            #     # blob_url = result.get('blob_url', '')
            #     # if blob_url:
            #     #     original_content = await self.retrieve_blob_content(blob_url)
            #     #     combined_texts += f"Original Content: {original_content}\n\n"
            #     # else:
            #     #     combined_texts += "No content found for this result.\n\n"
            #     summary = result.get('summary', 'no summary found')
            #     combined_texts += f"Summary: {summary}\n\n"

            # if not combined_texts.strip():
            #     return "No relevant documents found for the query."

            synthesized_response = await self.generate_llm_response(user_query, search_results, conversational_history)
            return synthesized_response

        except Exception as e:
            print(f"Error synthesizing response: {e}")
            return "Sorry, I couldn't generate a summary for the results."

    @time_it
    async def retrieve_blob_content(self, blob_url):
        print(f"Retrieving content from blob: {blob_url}")
        try:
            blob_client = BlobClient.from_blob_url(blob_url, credential=self.blob_access_key)
            blob_data_stream = await blob_client.download_blob()
            blob_data = await blob_data_stream.readall()
            return blob_data.decode('utf-8')

        except Exception as e:
            print(f"Error retrieving blob content: {e}")
            return "Error retrieving original content."