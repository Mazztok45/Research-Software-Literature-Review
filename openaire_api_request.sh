list_queries=("research AND software AND metadata"
"scientific AND software AND metadata"

"research AND software AND citation"
"scientific AND software AND citation"

"research AND software AND documentation"
"scientific AND software AND documentation"

"research AND software AND reproducibility"
"scientific AND software AND reproducibility"

"research AND software AND sustainability"
"scientific AND software AND sustainability"

"research AND software AND licensing"
"scientific AND software AND licensing"

"research AND software AND preservation"
"scientific AND software AND preservation"

"research AND software AND versioning"
"scientific AND software AND versioning"

"research AND software AND provenance"
"scientific AND software AND provenance"

"research AND software AND credit"
"scientific AND software AND credit"

"research AND software AND FAIR"
"scientific AND software AND FAIR"

"research AND software AND identifier"
"scientific AND software AND identifier"

"research AND software AND identifier"
"scientific AND software AND identifier"

)
)
for query in "${list_queries[@]}";
do
  # Replace spaces with underscores in the filename
  filename="${query// /_}.json"
  uv run openaire-py/client.py -s "$query" -e researchProducts --page-size 100 --max-results 10000 --output-format jsonl > "$filename"
done