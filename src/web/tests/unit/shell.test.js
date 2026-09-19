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

  it("shows the release version beside the home link on every page", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");
    const authenticationConditional = template.indexOf("{% if user.is_authenticated %}");
    const versionBadge = template.indexOf("{{ penni_more_version }}");

    expect(template).toContain(
      '<a class="btn btn-ghost px-0 text-xl font-semibold" href="/">Penni More</a>',
    );
    expect(template).toContain(
      '<span class="badge badge-ghost badge-sm">{{ penni_more_version }}</span>',
    );
    expect(versionBadge).toBeGreaterThan(-1);
    expect(versionBadge).toBeLessThan(authenticationConditional);
    expect(template.match(/penni_more_version/g)).toHaveLength(1);
    expect(template).not.toContain("<script");
  });

  it("provides an accessible POST dashboard filter without JavaScript", async () => {
    const template = await readFile(templateUrl("home.html"), "utf8");

    expect(template).toContain('aria-labelledby="page-title"');
    expect(template).toContain("Dashboard | Penni More");
    expect(template).toContain('<form method="post"');
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="date"');
    expect(template).toContain("dashboard_filter_form.accounts");
    expect(template).toContain("dashboard_filter_form.categories");
    expect(template).toContain("multiple");
    expect(template).toContain("Apply filters");
    expect(template).not.toContain("<script");
  });

  it("associates dashboard filter errors and instructions with native controls", async () => {
    const template = await readFile(templateUrl("home.html"), "utf8");

    expect(template).toContain('role="alert"');
    expect(template).toContain('aria-labelledby="dashboard-filter-error-title"');
    expect(template).toContain('aria-describedby="accounts-help');
    expect(template).toContain('aria-describedby="categories-help');
    expect(template).toContain('aria-invalid="true"');
    expect(template).toContain("dashboard_filter_form.non_field_errors");
    expect(template).toContain("Please correct the filters below");
  });

  it("renders text-first graph and empty states", async () => {
    const template = await readFile(templateUrl("home.html"), "utf8");

    expect(template).toContain("{% elif not graphs_available %}");
    expect(template).toContain("{% if dashboard_filter_form.accounts.field.queryset.exists %}");
    expect(template).toContain("Select at least one account");
    expect(template).toContain("No accounts available");
    expect(template).toContain("Create an account before using the dashboard graphs.");
    expect(template).toContain("{% url 'accounts:create' %}");
    expect(template).toContain(">Create account</a>");
    expect(template).toContain("Graphs are unavailable until the filter errors are corrected.");
    expect(template).toContain('aria-labelledby="income-expenses-title"');
    expect(template).toContain('aria-labelledby="category-expenses-title"');
    expect(template).toContain("{{ bar.label }}");
    expect(template).toContain("{{ bar.amount|floatformat:2 }} {{ dashboard_currency_code }}");
    expect(template).toContain("No categories selected.");
    expect(template.match(/aria-hidden="true"/g)).toHaveLength(2);
    expect(template).not.toContain('role="img"');
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

  it("offers one authenticated Accounts navigation link", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");

    expect(template.match(/\{% url 'accounts:list' %\}/g)).toHaveLength(1);
    expect(template).toContain(">Accounts</a>");
  });

  it("offers one authenticated Transactions navigation link", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");

    expect(template.match(/\{% url 'transactions:list' %\}/g)).toHaveLength(1);
    expect(template).toContain(">Transactions</a>");
  });

  it("announces Django status and error messages", async () => {
    const template = await readFile(templateUrl("base.html"), "utf8");

    expect(template).toContain("{% if messages %}");
    expect(template).toContain('aria-label="Status messages"');
    expect(template).toContain("alert-error");
    expect(template).toContain("alert-success");
  });
});
