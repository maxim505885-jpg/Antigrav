import urllib.request
import json

queries = [
    "indoor point cloud segmentation column beam",
    "Open3D-ML",
    "CloudCompare",
    "MinkowskiEngine",
    "Segment-Any-Point-Cloud",
]

for q in queries:
    url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(q)}&sort=stars&order=desc"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode("utf-8"))
        print(f"\n=== Query: {q} (Total: {data.get('total_count', 0)}) ===")
        for item in data.get("items", [])[:4]:
            name = item["full_name"]
            stars = item["stargazers_count"]
            desc = item.get("description") or "No description"
            url = item["html_url"]
            print(f"* [{name}]({url}) - STARS: {stars}")
            print(f"  {desc[:140]}...")
    except Exception as e:
        print(f"Error for {q}: {e}")
