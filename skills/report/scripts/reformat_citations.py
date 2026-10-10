import json
import os
import re
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python reformat_citations.py <file>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    ev_table_heading = "## Evidence table\n"
    if "## Citation footnotes" in content:
        print("Already reformatted (## Citation footnotes present); nothing to do")
        sys.exit(0)
    if ev_table_heading not in content:
        print("Could not find evidence table heading")
        sys.exit(1)

    body, rest = content.split(ev_table_heading, 1)

    cited_ids = set()
    for m in re.finditer(r'\[(E\d{4,})\]', body):
        cited_ids.add(m.group(1))

    before = len(re.findall(r'\[E\d{4,}\]', body))
    print(f"Markers before pass in body: {before}")
    
    new_body = re.sub(r'\[(E\d{4,})\]', r'[^\g<1>]', body)
    # Adjacent markers "[^A][^B]" parse as a reference link [text][label] in
    # MultiMarkdown/Marked 2 and swallow both citations; a comma keeps them apart.
    new_body = new_body.replace('][^E', '],[^E')

    # A research-skill writer's table has no URL column (writer.md asks for
    # claim, source, locator, tags); the URL then comes from evidence.jsonl
    # beside the report (2026-10-10: a five-column table failed with every
    # cited id "missing from table").
    url_by_id = {}
    ev_path = os.path.join(os.path.dirname(os.path.abspath(filepath)), "evidence.jsonl")
    if os.path.exists(ev_path):
        with open(ev_path, 'r', encoding='utf-8') as ef:
            for raw in ef:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if row.get("id"):
                    url_by_id[str(row["id"])] = str(row.get("url") or "")

    lines = rest.split('\n')
    new_lines = []

    header_found = False
    table_data = {}
    
    for i, line in enumerate(lines):
        if line.startswith('| ') and line.endswith(' |'):
            inner = line[2:-2]
            cells = inner.split(' | ')

            if len(cells) == 5 and cells[0] != 'id' and cells[0].startswith('E') \
                    and cells[0][1:].isdigit() and url_by_id:
                # five-column writer table: insert the url from evidence.jsonl
                cells = cells[:4] + [url_by_id.get(cells[0], "")] + cells[4:]

            if len(cells) == 6:
                if cells[0] == 'id':
                    new_lines.append('| id | claim | source (title, kind, family) | locator | tags |')
                else:
                    id_cell = cells[0]
                    claim = cells[1]
                    source = cells[2]
                    locator = cells[3]
                    url = cells[4]
                    tags = cells[5]
                    
                    if id_cell.startswith('E') and id_cell[1:].isdigit():
                        table_data[id_cell] = (claim, source, locator, url)
                        new_first = f"[{id_cell}]({url})"
                        new_row = f"| {new_first} | {claim} | {source} | {locator} | {tags} |"
                        # Assert 5 cells after rewriting
                        assert len(new_row[2:-2].split(' | ')) == 5
                        new_lines.append(new_row)
                    else:
                        print(f"Unexpected data row id format: {line}")
                        new_lines.append(line)
            elif len(cells) == 5 and header_found:
                new_lines.append(line)
            else:
                new_lines.append(line)
        elif line.startswith('|') and '---' in line:
            new_lines.append('|---|---|---|---|---|')
            header_found = True
        else:
            new_lines.append(line)

    missing = cited_ids - set(table_data.keys())
    if missing:
        print(f"Error: {len(missing)} cited ids missing from table: {missing}")
        sys.exit(1)

    footnotes = []
    footnotes.append("## Citation footnotes\n")
    
    written_defs = 0
    for id_val in sorted(list(cited_ids)):
        claim, source, locator, url = table_data[id_val]
        autolink_url = f"<{url}>" if url else ""
        
        fn = f"[^{id_val}]: {claim} — {source}, {locator}. {autolink_url}"
        if not autolink_url:
            fn = f"[^{id_val}]: {claim} — {source}, {locator}."
        footnotes.append(fn)
        written_defs += 1

    print(f"Cited ids: {len(cited_ids)}")
    print(f"Definitions written: {written_defs}")
    print(f"Table rows rewritten: {len(table_data)}")
    
    final_rest = '\n'.join(new_lines).rstrip()
    
    final_content = new_body + ev_table_heading + final_rest + "\n\n" + '\n\n'.join(footnotes) + "\n"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(final_content)

if __name__ == "__main__":
    main()
