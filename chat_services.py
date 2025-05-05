
from models import Chat, ChatMessage
from extensions import db
from services import query_collection, get_collection, generate_response, get_collection_documents_path ,query_specific_memory

from datetime import datetime
import ollama
import numpy as np
import os


def query_specific_memory(user_id, collection_id, memory_id, query_text):
    """Query a specific memory with a question"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return None, "Collection not found"
    
    # Find the specific memory in the collection
    memory_metadata = None
    memory_index = None
    for i, mem in enumerate(collection.get("memories", [])):
        if mem["id"] == memory_id:
            memory_metadata = mem
            memory_index = i
            break
    
    if not memory_metadata:
        return None, "Memory not found"
    
    try:
        # Generate embedding for the query
        response = ollama.embeddings(model="nomic-embed-text", prompt=query_text)
        query_embedding = np.array([response["embedding"]]).astype('float32')
        
        # Get text content of the memory
        memory_dir = get_collection_documents_path(user_id, collection_id)
        text_path = os.path.join(memory_dir, f"{memory_metadata['id']}.txt")
        
        with open(text_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Create the memory object with metadata and content
        memory = {
            "metadata": memory_metadata,
            "content": content,
            # We don't have a real distance since we're forcing this memory,
            # but we'll set a low value to indicate high relevance
            "distance": 0.0  
        }
        
        return [memory], None
    
    except Exception as e:
        return None, str(e)

def create_memory_chat_session(user_id, collection_id, memory_id):
    """Create a new chat session for a specific memory"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return None, "Collection not found"
    
    # Find the memory in the collection
    memory = None
    for mem in collection.get("memories", []):
        if mem["id"] == memory_id:
            memory = mem
            break
    
    if not memory:
        return None, "Memory not found"
    
    chat = Chat(
        user_id=user_id,
        collection_id=collection_id,
        memory_id=memory_id,
        title=f"Chat with {memory['title']}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    try:
        db.session.add(chat)
        db.session.commit()
        return chat, None
    except Exception as e:
        db.session.rollback()
        return None, str(e)

def create_chat_session(user_id, collection_id):
    """Create a new chat session for a user and collection"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return None, "Collection not found"
    
    chat = Chat(
        user_id=user_id,
        collection_id=collection_id,
        title=f"Chat with {collection['name']}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    try:
        db.session.add(chat)
        db.session.commit()
        return chat, None
    except Exception as e:
        db.session.rollback()
        return None, str(e)





def get_chat_sessions(user_id, collection_id=None):
    """Get all chat sessions for a user, optionally filtered by collection"""
    query = Chat.query.filter_by(user_id=user_id)
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    return query.order_by(Chat.updated_at.desc()).all()

def get_chat_messages(chat_id, user_id):
    """Get all messages for a specific chat session"""
    chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
    if not chat:
        return None, "Chat session not found"
    
    messages = ChatMessage.query.filter_by(chat_id=chat.id).order_by(ChatMessage.timestamp).all()
    return chat, messages

def add_message_to_chat(chat_id, user_id, content, is_user=True, relevant_memory_ids=None):
    """Add a new message to an existing chat session"""
    chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
    if not chat:
        return None, "Chat session not found"
    
    memory_ids_str = None
    if relevant_memory_ids:
        if isinstance(relevant_memory_ids, list):
            memory_ids_str = ",".join(str(id) for id in relevant_memory_ids)
        else:
            memory_ids_str = str(relevant_memory_ids)
    
    message = ChatMessage(
        chat_id=chat.id,
        content=content,
        is_user=is_user,
        timestamp=datetime.utcnow(),
        relevant_memory_ids=memory_ids_str
    )
    
    chat.updated_at = datetime.utcnow()
    
    try:
        db.session.add(message)
        db.session.commit()
        return message, None
    except Exception as e:
        db.session.rollback()
        return None, str(e)

def process_chat_query(chat_id, user_id, query_text):
    """Process a user query, store it, and generate a response"""
    chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
    if not chat:
        return None, "Chat session not found"
    
    # If this is a memory-specific chat, use the memory-specific query function
    if chat.memory_id:
        return process_memory_chat_query(chat_id, user_id, query_text)
    
    # Otherwise, proceed with collection-wide query as before
    user_message, error = add_message_to_chat(chat_id, user_id, query_text, is_user=True)
    if error:
        return None, error
    
    relevant_memories, error = query_collection(user_id, chat.collection_id, query_text)
    if error:
        return None, error
    
    response_text = generate_response(query_text, relevant_memories)
    
    memory_ids = [memory['metadata']['id'] for memory in relevant_memories]
    
    ai_message, error = add_message_to_chat(
        chat_id, 
        user_id, 
        response_text, 
        is_user=False,
        relevant_memory_ids=memory_ids
    )
    
    if error:
        return None, error
    
    return {
        "query": query_text,
        "response": response_text,
        "relevant_memories": [m["metadata"] for m in relevant_memories]
    }, None
    
def delete_chat_session(chat_id, user_id):
    """Delete a chat session and all its messages"""
    chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
    if not chat:
        return False, "Chat session not found"
    
    try:
        db.session.delete(chat)
        db.session.commit()
        return True, None
    except Exception as e:
        db.session.rollback()
        return False, str(e)

# Add to chat_services.py

def create_memory_chat_session(user_id, collection_id, memory_id):
    """Create a new chat session for a specific memory"""
    collection = get_collection(user_id, collection_id)
    if not collection:
        return None, "Collection not found"
    
    # Find the memory in the collection
    memory = None
    for mem in collection.get("memories", []):
        if mem["id"] == memory_id:
            memory = mem
            break
    
    if not memory:
        return None, "Memory not found"
    
    chat = Chat(
        user_id=user_id,
        collection_id=collection_id,
        title=f"Chat with {memory['title']}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        # Store the memory_id to indicate this is a single-memory chat
        memory_id=memory_id
    )
    
    try:
        db.session.add(chat)
        db.session.commit()
        return chat, None
    except Exception as e:
        db.session.rollback()
        return None, str(e)

# In process_memory_chat_query function in chat_services.py:
def process_memory_chat_query(chat_id, user_id, query_text):
    """Process a user query for a specific memory chat"""
    print(f"DEBUG: process_memory_chat_query called with chat_id={chat_id}, user_id={user_id}")
    
    chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
    print(f"DEBUG: Chat found: {chat}")
    
    if not chat:
        print("DEBUG: Chat session not found")
        return None, "Chat session not found"
    
    # Check if this is a memory-specific chat
    print(f"DEBUG: Chat memory_id: {chat.memory_id}")
    if not chat.memory_id:
        print("DEBUG: This is not a memory-specific chat")
        return None, "This is not a memory-specific chat"
    
    try:
        print(f"DEBUG: Adding user message to chat")
        user_message, error = add_message_to_chat(chat_id, user_id, query_text, is_user=True)
        if error:
            print(f"DEBUG: Error adding user message: {error}")
            return None, error
        
        print(f"DEBUG: Querying specific memory: collection_id={chat.collection_id}, memory_id={chat.memory_id}")
        memory_result, error = query_specific_memory(user_id, chat.collection_id, chat.memory_id, query_text)
        if error:
            print(f"DEBUG: Error querying memory: {error}")
            return None, error
        
        print(f"DEBUG: Generating response")
        response_text = generate_response(query_text, memory_result)
        
        print(f"DEBUG: Adding AI message to chat")
        ai_message, error = add_message_to_chat(
            chat_id, 
            user_id, 
            response_text, 
            is_user=False,
            relevant_memory_ids=chat.memory_id
        )
        
        if error:
            print(f"DEBUG: Error adding AI message: {error}")
            return None, error
        
        print(f"DEBUG: Returning successful response")
        return {
            "query": query_text,
            "response": response_text,
            "relevant_memories": [memory_result[0]["metadata"]] if memory_result else []
        }, None
    except Exception as e:
        print(f"DEBUG: Exception in process_memory_chat_query: {str(e)}")
        import traceback
        print(f"DEBUG: Traceback: {traceback.format_exc()}")
        return None, str(e)