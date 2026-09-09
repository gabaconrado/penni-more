import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

const loginTemplate = new URL("../../templates/registration/login.html", import.meta.url);

describe("the server-rendered login page", () => {
  it("submits only Django's email identifier, password, safe return target, and CSRF data", async () => {
    const template = await readFile(loginTemplate, "utf8");

    expect(template).toContain('method="post"');
    expect(template).toContain("{% url 'login' %}");
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="email"');
    expect(template).toContain('name="{{ form.username.html_name }}"');
    expect(template).toContain("value=\"{{ form.username.value|default_if_none:'' }}\"");
    expect(template).toContain('autocomplete="email"');
    expect(template).toContain('type="password"');
    expect(template).toContain('name="{{ form.password.html_name }}"');
    expect(template).toContain('autocomplete="current-password"');
    expect(template).not.toContain("autofocus");
    expect(template).toContain('type="hidden" name="next"');
    expect(template).not.toMatch(/register|recover|reset/i);
    expect(template).not.toContain("<script");
  });

  it("provides visible labels and programmatic error relationships", async () => {
    const template = await readFile(loginTemplate, "utf8");

    expect(template).toContain('for="{{ form.username.id_for_label }}"');
    expect(template).toContain('for="{{ form.password.id_for_label }}"');
    expect(template).toContain('id="{{ form.username.auto_id }}_error"');
    expect(template).toContain('id="{{ form.password.auto_id }}_error"');
    expect(template).toContain('aria-describedby="{{ form.username.auto_id }}_error"');
    expect(template).toContain('aria-describedby="{{ form.password.auto_id }}_error"');
    expect(template).toContain('role="alert"');
    expect(template).toContain('aria-labelledby="login-error-title"');
    expect(template).toContain("{{ form.non_field_errors }}");
  });
});
