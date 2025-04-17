list_queries=("research AND software AND metadata")
for query in "${list_queries[@]}";
do
  # Replace spaces with underscores in the filename
  filename="${query// /_}.json"
  uv run openaire-py/client.py -s "$query" -e researchProducts --page-size 100 --max-results 10000 --output-format jsonl > "$filename"
done