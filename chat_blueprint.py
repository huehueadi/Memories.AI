from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import Chat, ChatMessage
from services import get_collection
from chat_services import (
    create_chat_session, create_memory_chat_session,
    get_chat_sessions, get_chat_messages, 
    process_chat_query, process_memory_chat_query,
    delete_chat_session, create_diary_chat_session, get_diary_chat_sessions, process_diary_chat_query, 
)

from diary_services import get_diary_with_entries

chat_bp = Blueprint('chat', __name__, url_prefix='/api/collections')


diary_chat_bp = Blueprint('diary_chat', __name__, url_prefix='/api/diaries')

general_chat_bp = Blueprint('general_chat', __name__, url_prefix='/api')


@general_chat_bp.route('/recent-chats', methods=['GET'])
@login_required
def get_recent_chats():
    try:
        # Get a limited number of most recent chats across all collections
        limit = request.args.get('limit', default=5, type=int)
        
        # Query for recent chats, ordered by updated_at
        recent_chats = Chat.query.filter_by(
            user_id=current_user.id
        ).order_by(Chat.updated_at.desc()).limit(limit).all()
        
        # Format the response
        formatted_chats = []
        for chat in recent_chats:
            try:
                # Get collection name - handle potential errors
                collection = get_collection(current_user.id, chat.collection_id)
                collection_name = collection.get('name', 'Unknown Collection') if collection else 'Unknown Collection'
                
                # Base chat data without memory info
                chat_data = {
                    "id": chat.id,
                    "title": chat.title,
                    "collection_id": chat.collection_id,
                    "collection_name": collection_name,
                    "memory_id": chat.memory_id,
                    "memory_name": None,
                    "created_at": chat.created_at.isoformat(),
                    "updated_at": chat.updated_at.isoformat()
                }
                
                # Get memory name if applicable
                if chat.memory_id and collection and 'memories' in collection:
                    for memory in collection.get('memories', []):
                        if memory.get('id') == chat.memory_id:
                            chat_data["memory_name"] = memory.get('title', 'Unknown Memory')
                            break
                
                formatted_chats.append(chat_data)
            except Exception as chat_error:
                # Log individual chat errors but continue processing
                print(f"Error processing chat {chat.id}: {str(chat_error)}")
                continue
        
        return jsonify({
            "success": True,
            "chats": formatted_chats
        })
    except Exception as e:
        print(f"Error in get_recent_chats: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500




@general_chat_bp.route('/chats', methods=['GET'])
@login_required
def get_all_chats():
    try:
        chats = get_chat_sessions(current_user.id)
        return jsonify({
            "success": True,
            "chats": [{
                "id": chat.id,
                "title": chat.title,
                "collection_id": chat.collection_id,
                "created_at": chat.created_at.isoformat(),
                "updated_at": chat.updated_at.isoformat()
            } for chat in chats]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500





@chat_bp.route('/<collection_id>/memory/<memory_id>/chat/<chat_id>/messages', methods=['GET'])
@login_required
def get_memory_chat_messages(collection_id, memory_id, chat_id):
    chat = Chat.query.filter_by(
        id=chat_id,
        user_id=current_user.id,
        collection_id=collection_id,
        memory_id=memory_id
    ).first()
    
    if not chat:
        return jsonify({"success": False, "error": "Chat session not found"}), 404
    
    messages = ChatMessage.query.filter_by(chat_id=chat.id).order_by(ChatMessage.timestamp).all()
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id,
            "memory_id": chat.memory_id
        },
        "messages": [{
            "id": msg.id,
            "content": msg.content,
            "is_user": msg.is_user,
            "timestamp": msg.timestamp.isoformat(),
            "relevant_memory_ids": msg.relevant_memory_ids.split(",") if msg.relevant_memory_ids else []
        } for msg in messages]
    })

@chat_bp.route('/<collection_id>/chat', methods=['POST'])
@login_required
def create_chat(collection_id):
    chat, error = create_chat_session(current_user.id, collection_id)
    if error:
        return jsonify({"success": False, "error": error}), 404
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        }
    })

@chat_bp.route('/<collection_id>/chats', methods=['GET'])
@login_required
def get_chats(collection_id):
    chats = get_chat_sessions(current_user.id, collection_id)
    return jsonify({
        "success": True,
        "chats": [{
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        } for chat in chats]
    })

@chat_bp.route('/<collection_id>/chat/<chat_id>/messages', methods=['GET'])
@login_required
def get_messages(collection_id, chat_id):
    chat, messages = get_chat_messages(chat_id, current_user.id)
    if not chat:
        return jsonify({"success": False, "error": "Chat session not found"}), 404
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id
        },
        "messages": [{
            "id": msg.id,
            "content": msg.content,
            "is_user": msg.is_user,
            "timestamp": msg.timestamp.isoformat(),
            "relevant_memory_ids": msg.relevant_memory_ids.split(",") if msg.relevant_memory_ids else []
        } for msg in messages]
    })

@chat_bp.route('/<collection_id>/chat/<chat_id>/query', methods=['POST'])
@login_required
def process_query(collection_id, chat_id):
    data = request.json
    query = data.get('query', '')
    
    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400
    
    result, error = process_chat_query(chat_id, current_user.id, query)
    if error:
        return jsonify({"success": False, "error": error}), 500
    
    return jsonify({
        "success": True,
        "query": result["query"],
        "response": result["response"],
        "relevant_memories": result["relevant_memories"]
    })

@chat_bp.route('/<collection_id>/chat/<chat_id>', methods=['DELETE'])
@login_required
def delete_chat(collection_id, chat_id):
    success, error = delete_chat_session(chat_id, current_user.id)
    if not success:
        return jsonify({"success": False, "error": error}), 404
    
    return jsonify({
        "success": True,
        "message": "Chat session deleted successfully"
    })

# Add to chat_blueprint.py

@chat_bp.route('/<collection_id>/memory/<memory_id>/chat', methods=['POST'])
@login_required
def create_memory_chat(collection_id, memory_id):
    chat, error = create_memory_chat_session(current_user.id, collection_id, memory_id)
    if error:
        return jsonify({"success": False, "error": error}), 404
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id,
            "memory_id": chat.memory_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        }
    })

@chat_bp.route('/<collection_id>/memory/<memory_id>/chats', methods=['GET'])
@login_required
def get_memory_chats(collection_id, memory_id):
    chats = Chat.query.filter_by(
        user_id=current_user.id,
        collection_id=collection_id,
        memory_id=memory_id
    ).order_by(Chat.updated_at.desc()).all()
    
    return jsonify({
        "success": True,
        "chats": [{
            "id": chat.id,
            "title": chat.title,
            "collection_id": chat.collection_id,
            "memory_id": chat.memory_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        } for chat in chats]
    })

@chat_bp.route('/<collection_id>/memory/<memory_id>/chat/<chat_id>/query', methods=['POST'])
@login_required
def process_memory_query(collection_id, memory_id, chat_id):
    data = request.json
    query = data.get('query', '')
    
    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400
    
    # Verify this chat belongs to this memory
    chat = Chat.query.filter_by(
        id=chat_id,
        user_id=current_user.id,
        collection_id=collection_id,
        memory_id=memory_id
    ).first()
    
    if not chat:
        return jsonify({"success": False, "error": "Chat not found for this memory"}), 404
    
    result, error = process_memory_chat_query(chat_id, current_user.id, query)
    if error:
        return jsonify({"success": False, "error": error}), 500
    
    return jsonify({
        "success": True,
        "query": result["query"],
        "response": result["response"],
        "relevant_memories": result["relevant_memories"]
    })

@diary_chat_bp.route('/<int:diary_id>/chat', methods=['POST'])
@login_required
def create_diary_chat(diary_id):
    chat, error = create_diary_chat_session(current_user.id, diary_id)
    if error:
        return jsonify({"success": False, "error": error}), 404
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "diary_id": chat.diary_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        }
    })

@diary_chat_bp.route('/<int:diary_id>/chats', methods=['GET'])
@login_required
def get_diary_chats(diary_id):
    chats = get_diary_chat_sessions(current_user.id, diary_id)
    return jsonify({
        "success": True,
        "chats": [{
            "id": chat.id,
            "title": chat.title,
            "diary_id": chat.diary_id,
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()
        } for chat in chats]
    })

@diary_chat_bp.route('/<int:diary_id>/chat/<int:chat_id>/messages', methods=['GET'])
@login_required
def get_diary_chat_messages(diary_id, chat_id):
    chat, messages = get_chat_messages(chat_id, current_user.id)
    if not chat:
        return jsonify({"success": False, "error": "Chat session not found"}), 404
    
    if chat.diary_id != diary_id:
        return jsonify({"success": False, "error": "Chat does not belong to this diary"}), 404
    
    return jsonify({
        "success": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "diary_id": chat.diary_id
        },
        "messages": [{
            "id": msg.id,
            "content": msg.content,
            "is_user": msg.is_user,
            "timestamp": msg.timestamp.isoformat(),
            "relevant_entry_ids": msg.relevant_memory_ids.split(",") if msg.relevant_memory_ids else []
        } for msg in messages]
    })

@diary_chat_bp.route('/<int:diary_id>/chat/<int:chat_id>/query', methods=['POST'])
@login_required
def process_diary_query(diary_id, chat_id):
    data = request.json
    query = data.get('query', '')
    
    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400
    
    # Verify this chat belongs to this diary
    chat = Chat.query.filter_by(
        id=chat_id,
        user_id=current_user.id,
        diary_id=diary_id
    ).first()
    
    if not chat:
        return jsonify({"success": False, "error": "Chat not found for this diary"}), 404
    
    result, error = process_diary_chat_query(chat_id, current_user.id, query)
    if error:
        return jsonify({"success": False, "error": error}), 500
    
    return jsonify({
        "success": True,
        "query": result["query"],
        "response": result["response"],
        "relevant_entries": result["relevant_entries"]
    })
