import cv2
import numpy as np

def detect_plant_shape(image_path):
    # Read image
    img = cv2.imread(image_path)
    
    # Convert to HSV color space
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Define green color range
    lower_green = np.array([36, 25, 25])
    upper_green = np.array([86, 255, 255])
    
    # Create mask for green colors
    mask = cv2.inRange(hsv, lower_green, upper_green)
    
    # Apply morphological operations to clean mask
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Filter by size
    min_area = 100
    plant_contours = [c for c in contours if cv2.contourArea(c) > min_area]
    
    # Get largest contour (presumably the plant)
    if plant_contours:
        plant_contour = max(plant_contours, key=cv2.contourArea)
        
        # Calculate shape metrics
        area = cv2.contourArea(plant_contour)
        perimeter = cv2.arcLength(plant_contour, True)
        x, y, w, h = cv2.boundingRect(plant_contour)
        
        # Draw contour
        result = img.copy()
        cv2.drawContours(result, [plant_contour], -1, (0, 255, 0), 2)
        cv2.rectangle(result, (x, y), (x+w, y+h), (0, 0, 255), 2)
        
        # Display results
        cv2.imshow('Original', img)
        cv2.imshow('Mask', mask)
        cv2.imshow('Detected Plant', result)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        
        return {
            'area': area,
            'perimeter': perimeter,
            'width': w,
            'height': h,
            'aspect_ratio': w/h if h > 0 else 0,
            'contour': plant_contour
        }
    
    return None

# Usage
plant_metrics = detect_plant_shape('plant_image.jpg')
print(plant_metrics)