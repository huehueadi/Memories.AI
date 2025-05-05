from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from services import get_all_collections, get_collection, create_collection, delete_collection

collections_bp = Blueprint('collections', __name__, url_prefix='/api/collections')

@collections_bp.route('', methods=['GET'])
@login_required
def get_collections():
    collections = get_all_collections(current_user.id)
    return jsonify({
        "success": True,
        "collections": collections
    })

@collections_bp.route('', methods=['POST'])
@login_required
def create_new_collection():
    data = request.json
    name = data.get('name', '')
    description = data.get('description', '')
    
    if not name:
        return jsonify({"success": False, "error": "Collection name is required"}), 400
    
    collection_id, metadata = create_collection(current_user.id, name, description)
    
    return jsonify({
        "success": True,
        "collection": metadata
    })

@collections_bp.route('/<collection_id>', methods=['GET'])
@login_required
def get_collection_details(collection_id):
    collection = get_collection(current_user.id, collection_id)
    if not collection:
        return jsonify({"success": False, "error": "Collection not found"}), 404
    
    return jsonify({
        "success": True,
        "collection": collection
    })

@collections_bp.route('/<collection_id>', methods=['DELETE'])
@login_required
def delete_collection_route(collection_id):
    success = delete_collection(current_user.id, collection_id)
    if not success:
        return jsonify({"success": False, "error": "Collection not found"}), 404
    
    return jsonify({
        "success": True,
        "message": "Collection deleted successfully"
    })

