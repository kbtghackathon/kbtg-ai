"""
Recurring Summary REST API

This module provides REST API endpoints for recurring expense summaries.

Requirements: 10.1-10.10, 15.1-15.10
"""

import logging
from typing import Dict, Any
from uuid import UUID
from flask import Flask, request, jsonify, Blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dataclasses import asdict

from ..aggregator.aggregation_service import AggregationService

logger = logging.getLogger(__name__)


def _get_authenticated_user_id(request) -> UUID:
    """
    Extract authenticated user ID from request
    
    This function should extract the user ID from JWT token, session, or
    other authentication mechanism.
    
    Requirements: 15.2, 15.3
    
    Args:
        request: Flask request object
        
    Returns:
        UUID of authenticated user
        
    Raises:
        ValueError: If authentication token is missing or invalid
    """
    # Check for JWT token in Authorization header
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        raise ValueError("Missing Authorization header")
    
    if not auth_header.startswith('Bearer '):
        raise ValueError("Invalid Authorization header format")
    
    # Extract token
    token = auth_header[7:]  # Remove 'Bearer ' prefix
    
    # TODO: Implement actual JWT validation
    # For now, this is a placeholder that extracts user_id from a simple token
    # In production, use a library like PyJWT to validate the token:
    #
    # import jwt
    # try:
    #     payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    #     return UUID(payload['user_id'])
    # except jwt.InvalidTokenError:
    #     raise ValueError("Invalid authentication token")
    
    # Temporary implementation for development/testing
    # In development, we accept the token as the user_id directly
    try:
        return UUID(token)
    except ValueError:
        raise ValueError("Invalid authentication token format")


def create_api(db_connection) -> Flask:
    """
    Create Flask API with database connection
    
    Args:
        db_connection: Database connection object
        
    Returns:
        Flask app instance
    """
    app = Flask(__name__)
    aggregation_service = AggregationService(db_connection)
    
    # Requirement 15.10: Initialize rate limiter for API endpoints
    # This prevents brute force attacks by limiting requests per user/IP
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",  # In production, use Redis: "redis://localhost:6379"
        strategy="fixed-window"
    )
    
    @app.route('/api/v1/users/<user_id>/recurring-summary', methods=['GET'])
    @limiter.limit("10 per minute")  # Specific rate limit for this endpoint
    def get_recurring_summary(user_id: str):
        """
        Get recurring expenses summary for user
        
        Path Parameters:
            user_id: User UUID
            
        Query Parameters:
            current_salary: Current month salary (required)
            
        Returns:
            JSON response with recurring summary
            
        Requirements: 10.1-10.10, 15.1-15.10
        """
        try:
            # Requirement 15.2, 15.3: Authenticate user first
            try:
                authenticated_user_id = _get_authenticated_user_id(request)
            except ValueError as e:
                logger.warning(f"Authentication failed: {str(e)}")
                return jsonify({
                    "error": "Unauthorized",
                    "message": str(e)
                }), 401
            
            # Parse user_id
            # Requirement 10.2
            try:
                user_uuid = UUID(user_id)
            except ValueError:
                logger.warning(f"Invalid user_id format: {user_id}")
                return jsonify({
                    "error": "Invalid user_id format",
                    "message": "user_id must be a valid UUID"
                }), 400
            
            # Requirement 15.2, 15.3: Verify the requesting user_id matches the resource user_id
            if authenticated_user_id != user_uuid:
                logger.warning(
                    f"Authorization failed: User {authenticated_user_id} attempted to access "
                    f"data for user {user_uuid}"
                )
                return jsonify({
                    "error": "Forbidden",
                    "message": "You do not have permission to access this resource"
                }), 403
            
            # Get current_salary query parameter
            # Requirement 10.2
            current_salary_str = request.args.get('current_salary')
            
            if current_salary_str is None:
                logger.warning(f"Missing current_salary for user {user_id}")
                return jsonify({
                    "error": "Missing required parameter",
                    "message": "current_salary query parameter is required"
                }), 400
            
            try:
                current_salary = float(current_salary_str)
                
                if current_salary < 0:
                    raise ValueError("Salary cannot be negative")
                    
            except ValueError as e:
                logger.warning(
                    f"Invalid current_salary for user {user_id}: {current_salary_str}"
                )
                return jsonify({
                    "error": "Invalid parameter value",
                    "message": f"current_salary must be a non-negative number: {str(e)}"
                }), 400
            
            # Call aggregation service to generate summary
            # Requirement 10.2
            logger.info(
                f"Generating recurring summary for user {user_id}, "
                f"salary={current_salary:.2f}"
            )
            
            summary = aggregation_service.generate_summary(user_uuid, current_salary)
            
            # Convert to JSON response format
            # Requirements 10.3-10.9
            response_data = {
                "salary_this_month": summary.salary_this_month,  # Requirement 10.3
                "recurring_expenses": [  # Requirement 10.4
                    {
                        "category": exp.category,
                        "category_label_th": exp.category_label_th,
                        "amount": exp.amount,
                        "confidence": exp.confidence,
                        "recipient_key": exp.recipient_key
                    }
                    for exp in summary.recurring_expenses
                ],
                "total_recurring": summary.total_recurring,  # Requirement 10.5
                "remaining_after_reserve": summary.remaining_after_reserve,  # Requirement 10.6
                "pending_user_labels": [  # Requirement 10.7
                    {
                        "recipient_key": label.recipient_key,
                        "detected_amount": label.detected_amount,
                        "n_months_detected": label.n_months_detected,
                        "category_suggestions": label.category_suggestions,
                        "sample_transactions": label.sample_transactions
                    }
                    for label in summary.pending_user_labels
                ],
                "data_completeness_warning": summary.data_completeness_warning,  # Requirement 10.8
                "data_months_available": summary.data_months_available  # Requirement 10.9
            }
            
            logger.info(
                f"Successfully generated summary for user {user_id}: "
                f"{len(summary.recurring_expenses)} expenses, "
                f"total={summary.total_recurring:.2f}"
            )
            
            # Requirement 10.10: Return HTTP 200 status
            return jsonify(response_data), 200
            
        except Exception as e:
            logger.error(
                f"Error generating summary for user {user_id}: {str(e)}",
                exc_info=True
            )
            return jsonify({
                "error": "Internal server error",
                "message": "Failed to generate recurring summary"
            }), 500
    
    return app


def create_app_with_config(db_config: Dict[str, Any]) -> Flask:
    """
    Create Flask app with database configuration
    
    Args:
        db_config: Database configuration dictionary
        
    Returns:
        Flask app instance
    """
    import psycopg2
    
    # Create database connection
    db_connection = psycopg2.connect(**db_config)
    
    return create_api(db_connection)
