import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

const templateUrl = (name) => new URL(`../../templates/${name}`, import.meta.url);

describe("the server-rendered shell", () => {
  it("provides a named navigation landmark and keyboard skip link", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");

    expect(template).toContain('aria-label="Primary navigation"');
    expect(template).toContain('href="#main-content"');
    expect(template).toContain('id="main-content"');
    expect(template).toContain('tabindex="-1"');
    expect(template).toContain("flex min-h-screen flex-col");
  });

  it("labels the initial page and does not present unfinished feature controls", async () => {
    const template = await readFile(templateUrl("home.html"), "utf8");

    expect(template).toContain('aria-labelledby="page-title"');
    expect(template).toContain("Account and transaction\n          features will be added");
    expect(template).not.toContain("<form");
  });

  it("shows identity and a CSRF-protected POST logout only to authenticated users", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");

    expect(template).toContain("{% if user.is_authenticated %}");
    expect(template).toContain("{{ user.email }}");
    expect(template).toContain('method="post"');
    expect(template).toContain("{% url 'logout' %}");
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="submit">Sign out</button>');
  });
});
