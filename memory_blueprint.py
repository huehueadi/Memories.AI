from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from services import get_collection, process_memory, allowed_file, detect_file_type

memory_bp = Blueprint('memory', __name__, url_prefix='/api/collections')

@memory_bp.route('/<collection_id>/memories', methods=['POST'])
@login_required
def add_memory(collection_id):
    collection = get_collection(current_user.id, collection_id)
    if not collection:
        return jsonify({"success": False, "error": "Collection not found"}), 404
    
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400
    
    file = request.files['file']

    memory_type = request.form.get('type')
    title = request.form.get('title', 'Untitled Memory')
    description = request.form.get('description', '')
    
    if file.filename == '':
        return jsonify({"success": False, "error": "No selected file"}), 400
    
    if not memory_type:
        memory_type = detect_file_type(file)
        if not memory_type:
            return jsonify({
                "success": False, 
                "error": "Could not determine file type. Please specify type parameter or use a supported file extension."
            }), 400
    
    if memory_type not in ['audio', 'pdf', 'text']:
        return jsonify({"success": False, "error": "Invalid memory type"}), 400
    
    if not allowed_file(file.filename, memory_type):
        return jsonify({
            "success": False, 
            "error": f"Invalid file type. Allowed types for {memory_type}: {', '.join(ALLOWED_EXTENSIONS[memory_type])}"
        }), 400
    
    memory, error = process_memory(current_user.id, collection_id, file, memory_type, title, description)
    
    if error:
        return jsonify({"success": False, "error": error}), 500
    
    return jsonify({
        "success": True,
        "memory": memory,
        "detected_type": memory_type if not request.form.get('type') else None
    })

@memory_bp.route('/<collection_id>/memories/<memory_id>', methods=['GET'])
@login_required
def get_memory(collection_id, memory_id):
    collection = get_collection(current_user.id, collection_id)
    if not collection:
        return jsonify({"success": False, "error": "Collection not found"}), 404
    
    # Find the specific memory in the collection
    memory = None
    for mem in collection.get("memories", []):
        if mem["id"] == memory_id:
            memory = mem
            break
    
    if not memory:
        return jsonify({"success": False, "error": "Memory not found"}), 404
    
    return jsonify({
        "success": True,
        "memory": memory
    })