with open('frontend/src/pages/RecipeImport.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the endpoint from /all to standard so it filters analyzed ones
content = content.replace('`${baseUrl}/collection-posts/all?collection_id=${folderName}&since=0`', '`${baseUrl}/collection-posts?collection_id=${folderName}&since=0`')

# Fix activeTab resetting
content = content.replace("useState<'single' | 'bulk'>('single');", "useState<'single' | 'bulk'>(folderPosts.length > 0 ? 'bulk' : 'single');")

with open('frontend/src/pages/RecipeImport.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
