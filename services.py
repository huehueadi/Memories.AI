import ollama
import os
import uuid
import json
import shutil
import mimetypes
import tempfile
from datetime import datetime
import numpy as np
import faiss
import whisper
import fitz
from werkzeug.utils import secure_filename

# Initialize components
whisper_model = whisper.load_model("tiny")

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COLLECTIONS_DIR = os.path.join(BASE_DIR, 'collections')
os.makedirs(COLLECTIONS_DIR, exist_ok=True)
TEMP_DIR = os.path.join(BASE_DIR, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)

# Embedding dimension for vector database
EMBEDDING_DIMENSION = 768

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'audio': {'wav', 'mp3', 'ogg', 'm4a'},
    'pdf': {'pdf'},
    'text': {'txt', 'md', 'csv', 'json'}
}

# Mapping of MIME types to memory types
MIME_TYPE_MAP = {
    'audio/mpeg': 'audio',
    'audio/mp3': 'audio',
    'audio/ogg': 'audio',
    'audio/wav': 'audio',
    'audio/x-wav': 'audio',
    'audio/m4a': 'audio',
    'audio/mp4': 'audio',
    'application/pdf': 'pdf',
    'text/plain': 'text',
    'text/markdown': 'text',
    'text/csv': 'text',
    'application/json': 'text'
}

# Utility Functions
def detect_file_type(file):
    """Automatically detect the file type based on extension and MIME type"""
    filename = file.filename
    # Check file extension first
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    for type_key, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return type_key
    
    # If extension doesn't match, try MIME type
    mime_type = mimetypes.guess_type(filename)[0]
    if mime_type in MIME_TYPE_MAP:
        return MIME_TYPE_MAP[mime_type]
    
    # Default to text if we can't determine the type
    return None

def allowed_file(filename, file_type):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS.get(file_type, set())

# Path management functions
def get_user_collections_dir(user_id):
    """Get the directory for a specific user's collections"""
    return os.path.join(COLLECTIONS_DIR, f'user_{user_id}')

def get_collection_path(user_id, collection_id):
    """Get the path for a specific collection"""
    return os.path.join(get_user_collections_dir(user_id), collection_id)

def get_collection_metadata_path(user_id, collection_id):
    """Get the metadata file path for a specific collection"""
    return os.path.join(get_collection_path(user_id, collection_id), 'metadata.json')

def get_collection_index_path(user_id, collection_id):
    """Get the FAISS index path for a specific collection"""
    return os.path.join(get_collection_path(user_id, collection_id), 'index')

def get_collection_documents_path(user_id, collection_id):
    """Get the documents directory for a specific collection"""
    return os.path.join(get_collection_path(user_id, collection_id), 'documents')

# Collection Management Functions
def create_collection(user_id, name, description=""):
    """Create a new collection with unique ID"""
    collection_id = str(uuid.uuid4())
    
    # Ensure user directory exists
    user_collections_dir = get_user_collections_dir(user_id)
    os.makedirs(user_collections_dir, exist_ok=True)
    
    collection_path = get_collection_path(user_id, collection_id)
    
    # Create collection directory structure
    os.makedirs(collection_path, exist_ok=True)
    os.makedirs(get_collection_documents_path(user_id, collection_id), exist_ok=True)
    
    # Create metadata file
    metadata = {
        "id": collection_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "memories": []
    }
    
    with open(get_collection_metadata_path(user_id, collection_id), 'w') as f:
        json.dump(metadata, f)
    
    # Initialize empty FAISS index
    index = faiss.IndexFlatL2(EMBEDDING_DIMENSION)
    faiss.write_index(index, get_collection_index_path(user_id, collection_id))
    
    return collection_id, metadata

def get_all_collections(user_id):
    """Get list of all collections for a specific user"""
    collections = []
    user_collections_dir = get_user_collections_dir(user_id)
    
    if not os.path.exists(user_collections_dir):
        return collections
    
    for collection_id in os.listdir(user_collections_dir):
        metadata_path = get_collection_metadata_path(user_id, collection_id)
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                collections.append(json.load(f))
    return collections

def get_collection(user_id, collection_id):
    """Get collection metadata by ID"""
    metadata_path = get_collection_metadata_path(user_id, collection_id)
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r') as f:
            return json.load(f)
    return None

def delete_collection(user_id, collection_id):
    """Delete a collection and all its data"""
    collection_path = get_collection_path(user_id, collection_id)
    if os.path.exists(collection_path):
        shutil.rmtree(collection_path)
        return True
    return False

# Memory Processing Functions
def extract_text_from_pdf(pdf_path):
    """Extract text content from a PDF file"""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def process_memory(user_id, collection_id, file, memory_type, title, description=""):
    """Process a new memory and add it to the collection"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return None, "Collection not found"
    
    try:
        # Create a unique ID for the memory
        memory_id = str(uuid.uuid4())
        
        # Save the original file
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        saved_filename = f"{memory_id}.{file_ext}"
        memory_dir = get_collection_documents_path(user_id, collection_id)
        file_path = os.path.join(memory_dir, saved_filename)
        file.save(file_path)
        
        # Extract text based on memory type
        memory_text = ""
        diarization_data = None
        
        if memory_type == 'audio':
            try:
                # Try using the advanced diarization functionality
                from upload_blueprint import process_audio_file_with_diarization
                
                print(f"Processing audio with diarization: {file_path}")
                diarization_result = process_audio_file_with_diarization(file_path)
                
                if "error" in diarization_result:
                    # If diarization had an error but returned transcript
                    print(f"Diarization warning: {diarization_result['error']}")
                    memory_text = diarization_result.get("full_transcript", "")
                    # Store partial diarization data if available
                    diarization_data = diarization_result.get("segments", [])
                else:
                    # Successful diarization
                    memory_text = diarization_result.get("full_transcript", "")
                    diarization_data = diarization_result.get("segments", [])
                
                print(f"Diarization completed with {len(diarization_data) if diarization_data else 0} segments")
                
            except Exception as e:
                # Fallback to original Whisper transcription
                print(f"Diarization failed, falling back to basic transcription: {str(e)}")
                result = whisper_model.transcribe(file_path)
                memory_text = result["text"]
        
        elif memory_type == 'pdf':
            # Extract text from PDF
            memory_text = extract_text_from_pdf(file_path)
        elif memory_type == 'text':
            # Read text file directly
            with open(file_path, 'r', encoding='utf-8') as f:
                memory_text = f.read()
        
        # Create memory metadata
        memory_metadata = {
            "id": memory_id,
            "title": title,
            "description": description,
            "type": memory_type,
            "filename": saved_filename,
            "original_filename": filename,
            "created_at": datetime.now().isoformat(),
        }
        
        # Add diarization data if available
        if memory_type == 'audio' and diarization_data:
            memory_metadata["has_diarization"] = True
            memory_metadata["diarization_segments"] = diarization_data
        
        # Generate embedding for memory text
        try:
            response = ollama.embeddings(model="nomic-embed-text", prompt=memory_text)
            embedding = response["embedding"]
        except Exception as e:
            return None, f"Error generating embedding: {e}"
        
        # Save text content
        text_path = os.path.join(memory_dir, f"{memory_id}.txt")
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(memory_text)
        
        # Update collection's FAISS index
        index = faiss.read_index(get_collection_index_path(user_id, collection_id))
        index.add(np.array([embedding]).astype('float32'))
        faiss.write_index(index, get_collection_index_path(user_id, collection_id))
        
        # Update collection metadata
        collection["memories"].append(memory_metadata)
        with open(get_collection_metadata_path(user_id, collection_id), 'w') as f:
            json.dump(collection, f)
        
        return memory_metadata, None
    
    except Exception as e:
        return None, str(e)

# Chat and Query Functions
def query_collection(user_id, collection_id, query_text, top_k=3):
    """Query a collection with a question and get relevant memories"""
    collection = get_collection(user_id, collection_id)
    if not collection or not collection.get("memories"):
        return [], "Collection not found or empty"
    
    try:
        # Generate embedding for the query
        response = ollama.embeddings(model="nomic-embed-text", prompt=query_text)
        query_embedding = np.array([response["embedding"]]).astype('float32')
        
        # Load FAISS index
        index = faiss.read_index(get_collection_index_path(user_id, collection_id))
        
        # Get top k most similar memories
        k = min(top_k, len(collection["memories"]))
        distances, indices = index.search(query_embedding, k)
        
        # Retrieve memory content for each match
        memory_dir = get_collection_documents_path(user_id, collection_id)
        relevant_memories = []
        
        for i in range(k):
            memory_index = indices[0][i]
            memory_metadata = collection["memories"][memory_index]
            
            # Get text content
            text_path = os.path.join(memory_dir, f"{memory_metadata['id']}.txt")
            with open(text_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            relevant_memories.append({
                "metadata": memory_metadata,
                "content": content,
                "distance": float(distances[0][i])
            })
        
        return relevant_memories, None
    
    except Exception as e:
        return [], str(e)

def generate_response(query, relevant_memories):
    """Generate a response based on relevant memories"""
    if not relevant_memories:
        return "I don't have any relevant memories to answer your question."
    
    # Combine memory contents for context
    context = ""
    for memory in relevant_memories:
        context += f"Memory: {memory['metadata']['title']} (originally '{memory['metadata'].get('original_filename', 'unknown')}', type: {memory['metadata']['type']})\n{memory['content']}\n\n"
    
    try:
        # Use local LLM to generate response
        prompt = f"""
        You are an AI assistant that helps users interact with their personal memories.
        Based on the following memories and the user's question, provide a helpful response.
        
        Memories: 
        {context}
        
        User question: {query}
        
        Your response should include references to the specific memories you're using to answer.
        If the memory is from a specific file type (like audio or PDF), mention this in your response.
        
        Your response:
        """
        
        output = ollama.generate(
            model="llama3",  # Using a lightweight model - can be changed based on available models
            prompt=prompt
        )
        
        return output['response']
    
    except Exception as e:
        print(f"Error generating response: {e}")
        return f"I had trouble processing your question. Technical error: {str(e)}"

def query_specific_memory(user_id, collection_id, memory_id, query_text):
    """Query a specific memory with a question"""
    print(f"DEBUG: Starting query_specific_memory for memory_id={memory_id}")
    collection = get_collection(user_id, collection_id)
    if not collection:
        print("DEBUG: Collection not found")
        return None, "Collection not found"
    
    # Find the specific memory in the collection
    memory_metadata = None
    for mem in collection.get("memories", []):
        if mem["id"] == memory_id:
            memory_metadata = mem
            break
    
    if not memory_metadata:
        print("DEBUG: Memory not found")
        return None, "Memory not found"
    
    try:
        print("DEBUG: Getting memory content")
        # Get text content of the memory
        memory_dir = get_collection_documents_path(user_id, collection_id)
        text_path = os.path.join(memory_dir, f"{memory_metadata['id']}.txt")
        
        with open(text_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Create the memory object with metadata and content
        memory = {
            "metadata": memory_metadata,
            "content": content,
            "distance": 0.0  # Low value to indicate high relevance
        }
        
        print("DEBUG: Successfully created memory object")
        return [memory], None
    
    except Exception as e:
        print(f"DEBUG: Exception in query_specific_memory: {str(e)}")
        import traceback
        print(f"DEBUG: Traceback: {traceback.format_exc()}")
        return None, str(e)

def delete_memory(user_id, collection_id, memory_id):
    """Delete a memory from a collection"""
    try:
        # Get the collection
        collection = get_collection(user_id, collection_id)
        if not collection:
            return False, "Collection not found"
        
        # Find the memory in the collection
        memory_index = None
        for i, memory in enumerate(collection.get("memories", [])):
            if memory["id"] == memory_id:
                memory_index = i
                break
        
        if memory_index is None:
            return False, "Memory not found"
        
        # Remove the memory from collection metadata
        memory = collection["memories"].pop(memory_index)
        
        # Delete the memory files from disk
        memory_dir = get_collection_documents_path(user_id, collection_id)
        
        # Delete the original file
        original_file = os.path.join(memory_dir, memory["filename"])
        if os.path.exists(original_file):
            os.remove(original_file)
        
        # Delete the text content file
        text_file = os.path.join(memory_dir, f"{memory_id}.txt")
        if os.path.exists(text_file):
            os.remove(text_file)
        
        # Save the updated collection metadata
        with open(get_collection_metadata_path(user_id, collection_id), 'w') as f:
            json.dump(collection, f)
        
        # Update FAISS index
        # This is more complex as you'd need to rebuild the index without the deleted embedding
        # For simplicity, you might want to just rebuild the entire index
        rebuild_collection_index(user_id, collection_id)
        
        return True, None
    except Exception as e:
        return False, str(e)

def rebuild_collection_index(user_id, collection_id):
    """Rebuild the FAISS index for a collection"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return False
    
    # Create a new empty index
    index = faiss.IndexFlatL2(EMBEDDING_DIMENSION)
    
    # Add all memories back to the index
    for memory in collection.get("memories", []):
        memory_dir = get_collection_documents_path(user_id, collection_id)
        text_path = os.path.join(memory_dir, f"{memory['id']}.txt")
        
        # Read the memory text content
        with open(text_path, 'r', encoding='utf-8') as f:
            memory_text = f.read()
        
        # Generate embedding
        response = ollama.embeddings(model="nomic-embed-text", prompt=memory_text)
        embedding = response["embedding"]
        
        # Add to index
        index.add(np.array([embedding]).astype('float32'))
    
    # Save the updated index
    faiss.write_index(index, get_collection_index_path(user_id, collection_id))
    
    return True