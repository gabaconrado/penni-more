import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

const accountTemplate = (name) =>
  readFile(new URL(`../../templates/accounts/${name}`, import.meta.url), "utf8");

describe("the server-rendered account pages", () => {
  it("renders a responsive, structured account list and a useful empty state", async () => {
    const template = await accountTemplate("account_list.html");

    expect(template).toContain("{% if accounts %}");
    expect(template).toContain('class="overflow-x-auto"');
    expect(template).toContain('role="region"');
    expect(template).toContain("<table");
    expect(template.match(/scope="col"/g)).toHaveLength(4);
    expect(template).toContain('scope="row"');
    expect(template).toContain("{% url 'accounts:detail' account.pk %}");
    expect(template).toContain("account.owner_id == user.id");
    expect(template).toContain("No accounts yet");
    expect(template).toContain("Create your first account");
    expect(template).not.toContain("<script");
  });

  it("shows owner actions and recipients only inside an owner branch", async () => {
    const template = await accountTemplate("account_detail.html");

    expect(template).toContain("{{ account.owner.email }}");
    expect(template).toContain("{{ account.get_account_type_display }}");
    expect(template).toContain("No description provided.");
    expect(template).toContain("{% if is_owner %}");
    expect(template).toContain("share_form.email");
    expect(template).toContain("{{ share.recipient.email }}");
    expect(template).toContain("{% url 'accounts:update' account.pk %}");
    expect(template).toContain("{% url 'accounts:delete' account.pk %}");
    expect(template).toContain("{% url 'accounts:share' account.pk %}");
    expect(template).toContain("{% url 'accounts:revoke' account.pk share.pk %}");
  });

  it("uses POST and CSRF protection for every detail-page mutation", async () => {
    const template = await accountTemplate("account_detail.html");

    expect(template.match(/method="post"/g)).toHaveLength(2);
    expect(template.match(/\{% csrf_token %\}/g)).toHaveLength(2);
    expect(template).toContain('type="submit">Share account</button>');
    expect(template).toContain("Revoke access for {{ share.recipient.email }}");
    expect(template).toContain('type="email"');
    expect(template).toContain('autocomplete="email"');
  });

  it("preserves bound account values and associates every field error", async () => {
    const template = await accountTemplate("account_form.html");

    for (const field of ["name", "description", "account_type"]) {
      expect(template).toContain(`for="{{ form.${field}.id_for_label }}"`);
      expect(template).toContain(`id="{{ form.${field}.auto_id }}_error"`);
      expect(template).toContain(`aria-describedby="{{ form.${field}.auto_id }}_error"`);
    }
    expect(template).toContain("form.name.value|default_if_none:''");
    expect(template).toContain("form.description.value|default_if_none:''");
    expect(template).toContain("form.account_type.value == value");
    expect(template).not.toContain('name="owner"');
    expect(template).not.toContain("<script");
  });

  it("requires an explicit CSRF-protected POST to permanently delete", async () => {
    const template = await accountTemplate("account_confirm_delete.html");

    expect(template).toContain("cannot be undone");
    expect(template).toContain('method="post"');
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="submit">Permanently delete account</button>');
    expect(template).toContain("{% url 'accounts:detail' account.pk %}");
  });
});
