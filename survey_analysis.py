import pandas as pd
import matplotlib.pyplot as plt
import re
data = pd.read_csv("survey.csv")

# Convert the "Horodateur" column to datetime format
data['Horodateur'] = pd.to_datetime(data['Horodateur'], errors='coerce')


# Convert the "Horodateur" column to datetime format
data['Horodateur'] = pd.to_datetime(data['Horodateur'], errors='coerce')

# Handle missing values
for column in data.columns:
    if data[column].dtype == 'object':
        mode = data[column].mode()[0]  # Get most frequent value (mode)
        data[column].fillna(mode, inplace=True)
    else:
        data[column].fillna(data[column].median(), inplace=True)

# Visualize the distribution of ratings for key challenges (numerical data)
numerical_columns_to_plot = [
    'Rate from 0 (no challenge) to 5 (critical challenge) how much governance policies hinder research software infrastructure management:\n\nNote: "Strategy" refers to long-term planning alignment (e.g., mismatches between policy constraints and infrastructure roadmaps, inflexible prioritization rules, or barriers to adopting new technologies).  [Human resource]',
    'Rate from 0 (no challenge) to 5 (critical challenge) how much governance policies hinder research software infrastructure management:\n\nNote: "Strategy" refers to long-term planning alignment (e.g., mismatches between policy constraints and infrastructure roadmaps, inflexible prioritization rules, or barriers to adopting new technologies).  [Funding]',
    'Rate from 0 (no challenge) to 5 (critical challenge) how much governance policies hinder research software infrastructure management:\n\nNote: "Strategy" refers to long-term planning alignment (e.g., mismatches between policy constraints and infrastructure roadmaps, inflexible prioritization rules, or barriers to adopting new technologies).  [Strategy]'
]


# Create separate plots for each column in the list
for col in numerical_columns_to_plot:
    plt.figure(figsize=(10, 6))
    plt.hist(data[col], bins=5, alpha=0.6)

    # Extract text between brackets using regex
    rating_match = re.search(r'\[(.*?)\]', col)
    rating = rating_match.group(1) if rating_match else "N/A"

    plt.title(f'Distribution of Challenge Rating: {rating}')
    plt.xlabel('Challenge Rating')
    plt.ylabel('Frequency')
    plt.show()