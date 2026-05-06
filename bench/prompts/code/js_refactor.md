Refactor this JavaScript function for clarity without changing behavior.

```js
function getVisibleItems(items, q, includeArchived) {
  let r = [];
  for (let i = 0; i < items.length; i++) {
    if (!includeArchived && items[i].archived) continue;
    if (q && items[i].title.toLowerCase().indexOf(q.toLowerCase()) === -1 && items[i].body.toLowerCase().indexOf(q.toLowerCase()) === -1) continue;
    r.push(items[i]);
  }
  return r;
}
```

Return:
- refactored code
- one paragraph explaining the changes
- two edge cases to test
