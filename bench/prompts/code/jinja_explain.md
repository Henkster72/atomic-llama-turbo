Explain what this Jinja template does and identify two possible failure cases.

```jinja2
{% for post in posts %}
  <article class="post">
    <h2><a href="{{ post.url }}">{{ post.title }}</a></h2>
    {% if post.summary %}
      <p>{{ post.summary }}</p>
    {% else %}
      <p>{{ post.body[:180] }}...</p>
    {% endif %}
  </article>
{% endfor %}
```

Return:
- concise explanation
- two failure cases
- one safer rewrite
