"""
Merchant Dictionary Management API

This module provides REST API endpoints for managing the merchant category dictionary
and handling cache invalidation.

Requirements: 16.6
"""

import logging
from typing import Dict, Any
from uuid import UUID
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..categorizer.categorization_module import CategorizationModule

logger = logging.getLogger(__name__)


def _get_authenticated_user_id(request) -> UUID:
    """
    Extract authenticated user ID from request
    
    This should check for admin/management role authorization.
    
    Requirements: 15.7
    
    Args:
        request: Flask request object
        
    Returns:
        UUID of authenticated user
        
    Raises:
        ValueError: If authentication token is missing or invalid
        PermissionError: If user lacks required permissions
    """
    # Check for JWT token in Authorization header
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        raise ValueError("Missing Authorization header")
    
    if not auth_header.startswith('Bearer '):
        raise ValueError("Invalid Authorization header format")
    
    # Extract token
    token = auth_header[7:]  # Remove 'Bearer ' prefix
    
    # TODO: Implement actual JWT validation and role checking
    # In production, verify user has 'merchant_admin' or similar role
    
    try:
        user_id = UUID(token)
        # TODO: Check if user has merchant dictionary management role
        return user_id
    except ValueError:
        raise ValueError("Invalid authentication token format")


def create_merchant_api(db_connection) -> Flask:
    """
    Create Flask API for merchant dictionary management
    
    Args:
        db_connection: Database connection object
        
    Returns:
        Flask app instance
        
    Requirements: 16.6
    """
    app = Flask(__name__)
    
    # Rate limiting
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["100 per day", "20 per hour"],
        storage_uri="memory://",
    )
    
    @app.route('/api/v1/admin/merchant-dictionary/invalidate-cache', methods=['POST'])
    @limiter.limit("5 per minute")
    def invalidate_cache():
        """
        Invalidate merchant dictionary cache
        
        This endpoint should be called after updating merchant dictionary entries
        to ensure all categorization modules use the latest data.
        
        Requirements: 16.6
        
        Returns:
            JSON response with success status
        """
        try:
            # Authenticate user
            try:
                authenticated_user_id = _get_authenticated_user_id(request)
            except ValueError as e:
                logger.warning(f"Authentication failed: {str(e)}")
                return jsonify({
                    "error": "Unauthorized",
                    "message": str(e)
                }), 401
            except PermissionError as e:
                logger.warning(f"Authorization failed: {str(e)}")
                return jsonify({
                    "error": "Forbidden",
                    "message": "Insufficient permissions for this operation"
                }), 403
            
            # Invalidate cache
            CategorizationModule.invalidate_cache()
            
            logger.info(
                f"Merchant dictionary cache invalidated by user {authenticated_user_id}"
            )
            
            return jsonify({
                "success": True,
                "message": "Merchant dictionary cache invalidated successfully"
            }), 200
            
        except Exception as e:
            logger.error(
                f"Error invalidating cache: {str(e)}",
                exc_info=True
            )
            return jsonify({
                "error": "Internal server error",
                "message": "Failed to invalidate cache"
            }), 500
    
    @app.route('/api/v1/admin/merchant-dictionary', methods=['POST'])
    @limiter.limit("10 per minute")
    def add_merchant_entry():
        """
        Add new merchant dictionary entry
        
        This endpoint adds a new merchant-category mapping and invalidates the cache.
        
        Requirements: 15.7, 16.6
        
        Request Body:
            {
                "keyword": "NETFLIX",
                "match_type": "substring",
                "category": "subscription",
                "category_label_th": "ค่าบอกรับ",
                "priority": 10
            }
        
        Returns:
            JSON response with success status
        """
        try:
            # Authenticate user
            try:
                authenticated_user_id = _get_authenticated_user_id(request)
            except ValueError as e:
                logger.warning(f"Authentication failed: {str(e)}")
                return jsonify({
                    "error": "Unauthorized",
                    "message": str(e)
                }), 401
            except PermissionError as e:
                logger.warning(f"Authorization failed: {str(e)}")
                return jsonify({
                    "error": "Forbidden",
                    "message": "Insufficient permissions for this operation"
                }), 403
            
            # Validate request body
            data = request.get_json()
            
            if not data:
                return jsonify({
                    "error": "Invalid request",
                    "message": "Request body must be JSON"
                }), 400
            
            required_fields = ['keyword', 'match_type', 'category', 'priority']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                return jsonify({
                    "error": "Invalid request",
                    "message": f"Missing required fields: {', '.join(missing_fields)}"
                }), 400
            
            # Insert into database
            cursor = db_connection.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO merchant_category_dict 
                    (keyword, match_type, category, category_label_th, priority, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    data['keyword'],
                    data['match_type'],
                    data['category'],
                    data.get('category_label_th', data['category']),
                    data['priority'],
                    True
                ))
                
                db_connection.commit()
                
                # Invalidate cache after successful insert
                CategorizationModule.invalidate_cache()
                
                logger.info(
                    f"Merchant dictionary entry added by user {authenticated_user_id}: "
                    f"keyword={data['keyword']}, category={data['category']}"
                )
                
                return jsonify({
                    "success": True,
                    "message": "Merchant dictionary entry added successfully"
                }), 201
                
            except Exception as e:
                db_connection.rollback()
                logger.error(f"Database error: {str(e)}")
                return jsonify({
                    "error": "Database error",
                    "message": "Failed to add merchant dictionary entry"
                }), 500
            finally:
                cursor.close()
                
        except Exception as e:
            logger.error(
                f"Error adding merchant entry: {str(e)}",
                exc_info=True
            )
            return jsonify({
                "error": "Internal server error",
                "message": "Failed to add merchant dictionary entry"
            }), 500
    
    return app
