#!/usr/bin/env python3
"""
Seed Merchant Dictionary Script
Purpose: Initialize common Thai merchant-to-category mappings
Requirements: 29.1-29.8

This script populates the merchant_category_dict table with 58 entries covering:
- Mobile operators (AIS, True, DTAC)
- Internet/fiber providers (3BB, True Online, AIS Fibre)
- Streaming subscriptions (Netflix, Spotify, YouTube Premium, Disney+)
- Utilities (electricity, water - Thai and English names)
- Insurance companies (AIA, FWD, Muang Thai, Prudential)
- E-wallets and food delivery (TrueMoney, ShopeeFood, GrabPay, Foodpanda)
- Gym memberships (Fitness First, True Fitness, etc.)
"""

import os
import sys
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# Merchant dictionary seed data
# Format: (keyword, match_type, category, category_label_th, priority)
MERCHANT_SEED_DATA: List[Tuple[str, str, str, str, int]] = [
    # ========================================================================
    # Mobile Operators - ค่าโทรศัพท์
    # ========================================================================
    ('AIS', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    ('TRUE', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    ('DTAC', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    ('ทรูมูฟ', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    ('ดีแทค', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    ('เอไอเอส', 'substring', 'mobile', 'ค่าโทรศัพท์', 10),
    
    # ========================================================================
    # Internet Providers - ค่าเน็ต
    # ========================================================================
    ('3BB', 'substring', 'internet', 'ค่าเน็ต', 10),
    ('TRUEONLINE', 'substring', 'internet', 'ค่าเน็ต', 10),
    ('TRUE ONLINE', 'substring', 'internet', 'ค่าเน็ต', 10),
    ('AISFIBRE', 'substring', 'internet', 'ค่าเน็ต', 10),
    ('AIS FIBRE', 'substring', 'internet', 'ค่าเน็ต', 10),
    ('TOT', 'substring', 'internet', 'ค่าเน็ต', 20),
    ('NT', 'substring', 'internet', 'ค่าเน็ต', 30),
    
    # ========================================================================
    # Streaming Subscriptions - ค่าสมาชิก
    # ========================================================================
    ('NETFLIX', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('SPOTIFY', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('YOUTUBE PREMIUM', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('YOUTUBE', 'substring', 'subscription', 'ค่าสมาชิก', 20),
    ('DISNEY+', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('DISNEY PLUS', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('LINE TV', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('VIU', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('HBO GO', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('APPLE MUSIC', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('JOOX', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('AMAZON PRIME', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('ICLOUD', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('GOOGLE ONE', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    ('DROPBOX', 'substring', 'subscription', 'ค่าสมาชิก', 10),
    
    # ========================================================================
    # Utilities - ค่าสาธารณูปโภค
    # ========================================================================
    ('การไฟฟ้า', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('MEA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('PEA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('METROPOLITAN ELECTRICITY', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('PROVINCIAL ELECTRICITY', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('การประปา', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('MWA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('PWA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('METROPOLITAN WATERWORKS', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    ('PROVINCIAL WATERWORKS', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10),
    
    # ========================================================================
    # Insurance - ค่าประกัน
    # ========================================================================
    ('AIA', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('FWD', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('MUANGTHAI', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('เมืองไทย', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('PRUDENTIAL', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('BANGKOK INSURANCE', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('ALLIANZ', 'substring', 'insurance', 'ค่าประกัน', 10),
    ('ประกันภัย', 'substring', 'insurance', 'ค่าประกัน', 20),
    
    # ========================================================================
    # E-wallets and Food Delivery - แอปฯ อาหาร
    # Note: These should be filtered as FREQUENT_SMALL_SPEND
    # ========================================================================
    ('TRUEMONEY WALLET', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    ('TRUEMONEY', 'substring', 'food_delivery', 'แอปฯ อาหาร', 20),
    ('SHOPEEFOOD', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    ('GRABPAY', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    ('GRAB', 'substring', 'food_delivery', 'แอปฯ อาหาร', 20),
    ('FOODPANDA', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    ('LINEMAN', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    ('ROBINHOOD', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10),
    
    # ========================================================================
    # Gym Memberships - ค่าฟิตเนส
    # ========================================================================
    ('FITNESS FIRST', 'substring', 'gym', 'ค่าฟิตเนส', 10),
    ('TRUE FITNESS', 'substring', 'gym', 'ค่าฟิตเนส', 10),
    ('VIRGIN ACTIVE', 'substring', 'gym', 'ค่าฟิตเนส', 10),
    ('CELEBRITY FITNESS', 'substring', 'gym', 'ค่าฟิตเนส', 10),
]


def seed_merchant_dictionary(db_connection):
    """
    Seed the merchant_category_dict table with common Thai merchants.
    
    Args:
        db_connection: Active database connection with cursor support
        
    Returns:
        int: Number of records inserted
    """
    cursor = db_connection.cursor()
    
    # Clear existing seed data (optional - comment out if you want to preserve existing)
    clear_sql = """
    DELETE FROM merchant_category_dict WHERE keyword IN (
      'AIS', 'TRUE', 'DTAC', '3BB', 'TRUEONLINE', 'AISFIBRE', 
      'NETFLIX', 'SPOTIFY', 'YOUTUBE', 'DISNEY', 
      'การไฟฟ้า', 'MEA', 'PEA', 'การประปา', 'MWA',
      'AIA', 'FWD', 'MUANGTHAI', 'PRUDENTIAL'
    )
    """
    cursor.execute(clear_sql)
    
    # Insert seed data
    insert_sql = """
    INSERT INTO merchant_category_dict 
      (keyword, match_type, category, category_label_th, priority, is_active)
    VALUES
      (%s, %s, %s, %s, %s, TRUE)
    """
    
    cursor.executemany(insert_sql, MERCHANT_SEED_DATA)
    db_connection.commit()
    
    inserted_count = cursor.rowcount
    print(f"✅ Successfully inserted {inserted_count} merchant dictionary entries")
    
    # Verification query
    cursor.execute("""
        SELECT category, category_label_th, COUNT(*) as count
        FROM merchant_category_dict
        WHERE is_active = TRUE
        GROUP BY category, category_label_th
        ORDER BY category
    """)
    
    print("\n📊 Merchant Dictionary Summary:")
    print("-" * 60)
    print(f"{'Category':<20} {'Thai Label':<20} {'Count':>10}")
    print("-" * 60)
    
    total = 0
    for row in cursor.fetchall():
        category, label_th, count = row
        print(f"{category:<20} {label_th:<20} {count:>10}")
        total += count
    
    print("-" * 60)
    print(f"{'TOTAL':<40} {total:>10}")
    print("-" * 60)
    
    cursor.close()
    return inserted_count


if __name__ == '__main__':
    import psycopg2
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Connect to database
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            port=os.getenv('DB_PORT', 5432),
            database=os.getenv('DB_NAME', 'recurring_expense_db'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', '')
        )
        
        print("🔌 Connected to database")
        
        # Run seed function
        count = seed_merchant_dictionary(conn)
        
        print(f"\n✨ Seed completed successfully! {count} entries inserted.")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
