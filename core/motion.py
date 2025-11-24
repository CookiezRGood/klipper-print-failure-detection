def is_toolhead_still(last_position, current_position, threshold=0.01):
    movement = sum(abs(current_position[i] - last_position[i]) for i in range(3))
    return movement < threshold
  
