-- ============================================================================
-- Seed Data: Merchant Category Dictionary
-- Purpose: Initialize common Thai merchant-to-category mappings
-- Requirements: 29.1-29.8
-- ============================================================================
-- This seed script creates 48 merchant dictionary entries covering:
-- - Mobile operators (AIS, True, DTAC)
-- - Internet/fiber providers (3BB, True Online, AIS Fibre)
-- - Streaming subscriptions (Netflix, Spotify, YouTube Premium, Disney+)
-- - Utilities (electricity, water - Thai and English names)
-- - Insurance companies (AIA, FWD, Muang Thai, Prudential)
-- - E-wallets and food delivery (TrueMoney, ShopeeFood, GrabPay, Foodpanda)
-- - Other recurring expenses (gym, cloud storage, etc.)
-- ============================================================================

-- Clear existing seed data if re-running
DELETE FROM merchant_category_dict WHERE keyword IN (
  'AIS', 'TRUE', 'DTAC', '3BB', 'TRUEONLINE', 'AISFIBRE', 
  'NETFLIX', 'SPOTIFY', 'YOUTUBE', 'DISNEY', 
  'การไฟฟ้า', 'MEA', 'PEA', 'การประปา', 'MWA',
  'AIA', 'FWD', 'MUANGTHAI', 'PRUDENTIAL'
);

-- ============================================================================
-- Category: mobile - Mobile Phone Operators
-- Thai Label: ค่าโทรศัพท์
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('AIS', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE),
  ('TRUE', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE),
  ('DTAC', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE),
  ('ทรูมูฟ', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE),
  ('ดีแทค', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE),
  ('เอไอเอส', 'substring', 'mobile', 'ค่าโทรศัพท์', 10, TRUE);

-- ============================================================================
-- Category: internet - Internet/Fiber Providers
-- Thai Label: ค่าเน็ต
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('3BB', 'substring', 'internet', 'ค่าเน็ต', 10, TRUE),
  ('TRUEONLINE', 'substring', 'internet', 'ค่าเน็ต', 10, TRUE),
  ('TRUE ONLINE', 'substring', 'internet', 'ค่าเน็ต', 10, TRUE),
  ('AISFIBRE', 'substring', 'internet', 'ค่าเน็ต', 10, TRUE),
  ('AIS FIBRE', 'substring', 'internet', 'ค่าเน็ต', 10, TRUE),
  ('TOT', 'substring', 'internet', 'ค่าเน็ต', 20, TRUE),
  ('NT', 'substring', 'internet', 'ค่าเน็ต', 30, TRUE);

-- ============================================================================
-- Category: subscription - Streaming and Digital Subscriptions
-- Thai Label: ค่าสมาชิก
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('NETFLIX', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('SPOTIFY', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('YOUTUBE PREMIUM', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('YOUTUBE', 'substring', 'subscription', 'ค่าสมาชิก', 20, TRUE),
  ('DISNEY+', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('DISNEY PLUS', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('LINE TV', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('VIU', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('HBO GO', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('APPLE MUSIC', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('JOOX', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('AMAZON PRIME', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('ICLOUD', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('GOOGLE ONE', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE),
  ('DROPBOX', 'substring', 'subscription', 'ค่าสมาชิก', 10, TRUE);

-- ============================================================================
-- Category: utility - Electricity and Water Utilities
-- Thai Label: ค่าสาธารณูปโภค
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('การไฟฟ้า', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('MEA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('PEA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('METROPOLITAN ELECTRICITY', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('PROVINCIAL ELECTRICITY', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('การประปา', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('MWA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('PWA', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('METROPOLITAN WATERWORKS', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE),
  ('PROVINCIAL WATERWORKS', 'substring', 'utility', 'ค่าสาธารณูปโภค', 10, TRUE);

-- ============================================================================
-- Category: insurance - Insurance Companies
-- Thai Label: ค่าประกัน
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('AIA', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('FWD', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('MUANGTHAI', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('เมืองไทย', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('PRUDENTIAL', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('BANGKOK INSURANCE', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('ALLIANZ', 'substring', 'insurance', 'ค่าประกัน', 10, TRUE),
  ('ประกันภัย', 'substring', 'insurance', 'ค่าประกัน', 20, TRUE);

-- ============================================================================
-- Category: food_delivery - E-wallets and Food Delivery (NOT recurring bills)
-- Thai Label: แอปฯ อาหาร
-- Note: These are tagged for reference but should be filtered as FREQUENT_SMALL_SPEND
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('TRUEMONEY WALLET', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE),
  ('TRUEMONEY', 'substring', 'food_delivery', 'แอปฯ อาหาร', 20, TRUE),
  ('SHOPEEFOOD', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE),
  ('GRABPAY', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE),
  ('GRAB', 'substring', 'food_delivery', 'แอปฯ อาหาร', 20, TRUE),
  ('FOODPANDA', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE),
  ('LINEMAN', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE),
  ('ROBINHOOD', 'substring', 'food_delivery', 'แอปฯ อาหาร', 10, TRUE);

-- ============================================================================
-- Category: gym - Fitness and Gym Memberships
-- Thai Label: ค่าฟิตเนส
-- ============================================================================
INSERT INTO merchant_category_dict 
  (keyword, match_type, category, category_label_th, priority, is_active) 
VALUES
  ('FITNESS FIRST', 'substring', 'gym', 'ค่าฟิตเนส', 10, TRUE),
  ('TRUE FITNESS', 'substring', 'gym', 'ค่าฟิตเนส', 10, TRUE),
  ('VIRGIN ACTIVE', 'substring', 'gym', 'ค่าฟิตเนส', 10, TRUE),
  ('CELEBRITY FITNESS', 'substring', 'gym', 'ค่าฟิตเนส', 10, TRUE);

-- ============================================================================
-- Verification Query
-- ============================================================================
-- To verify the seed data, run:
-- SELECT category, category_label_th, COUNT(*) as count
-- FROM merchant_category_dict
-- WHERE is_active = TRUE
-- GROUP BY category, category_label_th
-- ORDER BY category;

-- Expected results:
-- category       | category_label_th  | count
-- ---------------|-------------------|-------
-- food_delivery  | แอปฯ อาหาร         | 8
-- gym            | ค่าฟิตเนส          | 4
-- insurance      | ค่าประกัน          | 8
-- internet       | ค่าเน็ต            | 7
-- mobile         | ค่าโทรศัพท์        | 6
-- subscription   | ค่าสมาชิก          | 15
-- utility        | ค่าสาธารณูปโภค      | 10
-- ---------------|-------------------|-------
-- TOTAL:                             | 58
