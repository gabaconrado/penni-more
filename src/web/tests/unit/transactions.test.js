import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

const transactionTemplate = (name) =>
  readFile(new URL(`../../templates/transactions/${name}`, import.meta.url), "utf8");

describe("the server-rendered transaction pages", () => {
  it("renders filters, privacy-safe accounts, empty states, and pagination", async () => {
    const template = await transactionTemplate("transaction_list.html");

    expect(template).toContain("{% for row in page_obj.object_list %}");
    expect(template).toContain('class="overflow-x-auto"');
    expect(template).toContain('aria-label="Transactions"');
    expect(template.match(/scope="col"/g)).toHaveLength(4);
    expect(template).toContain('scope="row"');
    expect(template).toContain("{% if row.source.is_private %}");
    expect(template).toContain("{% if row.target.is_private %}");
    expect(template.match(/Private account/g)).toHaveLength(2);
    expect(template).toContain('href="{{ row.source.url }}"');
    expect(template).toContain('href="{{ row.target.url }}"');
    expect(template).not.toContain("row.source.pk");
    expect(template).not.toContain("row.target.pk");
    expect(template).toContain("No transactions yet");
    expect(template).toContain("No transactions match these filters");
    expect(template).toContain("Filters were not applied");
    expect(template).toContain("The attempted filters were not applied.");
    expect(template).toContain("{% if filters_active %}");
    expect(template).toContain(
      "Your previous validated filters remain active, and the displayed results use them.",
    );
    expect(template).toContain("No filters are currently active.");
    expect(template).toContain('aria-label="Transaction pages"');
    expect(template).toContain("?page={{ page_obj.previous_page_number }}");
    expect(template).toContain("?page={{ page_obj.next_page_number }}");
    expect(template).not.toContain("<script");
  });

  it("uses POST forms with CSRF for applying and clearing session filters", async () => {
    const template = await transactionTemplate("transaction_list.html");

    expect(template).toContain("{% url 'transactions:filters' %}");
    expect(template).toContain("{% url 'transactions:filters-clear' %}");
    expect(template.match(/method="post"/g).length).toBeGreaterThanOrEqual(3);
    expect(template.match(/\{% csrf_token %\}/g).length).toBeGreaterThanOrEqual(3);
    expect(template).toContain('type="month"');
    for (const field of ["account", "month", "additional_key", "additional_value"]) {
      expect(template).toContain(`for="{{ filter_form.${field}.id_for_label }}"`);
      expect(template).toContain(`id="{{ filter_form.${field}.auto_id }}_error"`);
      expect(template).toContain(`filter_form.${field}.value`);
    }
  });

  it("renders complete semantic detail data and authorization-controlled actions", async () => {
    const template = await transactionTemplate("transaction_detail.html");

    expect(template).toContain("<dl");
    expect(template).toContain("{{ transaction.get_transaction_type_display }}");
    expect(template).toContain("{{ transaction.category.name }}");
    expect(template).toContain(
      "{{ transaction.amount|floatformat:2 }} {{ transaction.amount_currency_code }}",
    );
    expect(template).toContain("{{ transaction.created_by.email }}");
    expect(template.match(/ UTC/g)).toHaveLength(2);
    expect(template).toContain("{% if is_future %}");
    expect(template).toContain("will not affect current balances until its date");
    expect(template).toContain("{% for key, value in additional_data_pairs %}");
    expect(template).toContain("{% if presentation.source.is_private %}");
    expect(template).toContain("{% if presentation.target.is_private %}");
    expect(template).not.toContain("presentation.source.pk");
    expect(template).not.toContain("presentation.target.pk");
    expect(template).toContain("{% if can_edit or can_delete %}");
    expect(template).toContain("{% if can_edit %}");
    expect(template).toContain("{% if can_delete %}");
  });

  it("associates transaction form errors and preserves every safe submitted value", async () => {
    const template = await transactionTemplate("transaction_form.html");
    const fields = [
      "transaction_type",
      "name",
      "description",
      "category",
      "date",
      "amount",
      "account",
      "target_account",
      "additional_data",
    ];

    for (const field of fields) {
      expect(template).toContain(`for="{{ form.${field}.id_for_label }}"`);
      expect(template).toContain(`id="{{ form.${field}.auto_id }}_error"`);
      expect(template).toContain(`form.${field}.value`);
    }
    expect(template).toContain(
      'aria-describedby="transaction-type-help{% if form.transaction_type.errors %} {{ form.transaction_type.auto_id }}_error{% endif %}"',
    );
    for (const field of ["amount", "account", "target_account", "additional_data"]) {
      expect(template).toContain(`{{ form.${field}.auto_id }}_error{% endif %}"`);
    }
    expect(template).toContain('inputmode="decimal"');
    expect(template).toContain('pattern="[0-9]+\\.[0-9]{2}"');
    expect(template).toContain('type="date"');
    expect(template).toContain("Keep private account");
    expect(template).toContain("one key = value pair per line");
    expect(template).not.toContain('name="created_by"');
    expect(template).not.toContain('name="created_at"');
    expect(template).not.toContain("<script");
  });

  it("requires an explicit CSRF-protected POST to delete a transaction", async () => {
    const template = await transactionTemplate("transaction_confirm_delete.html");

    expect(template).toContain("cannot be undone");
    expect(template).toContain('method="post"');
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="submit">Permanently delete transaction</button>');
    expect(template).toContain("{% if presentation.source.is_private %}");
    expect(template).toContain("{% if presentation.target.is_private %}");
    expect(template).toContain(
      "{{ transaction.amount|floatformat:2 }} {{ transaction.amount_currency_code }}",
    );
  });

  it("documents bounded CSV input and submits a multipart preview request", async () => {
    const template = await transactionTemplate("transaction_import.html");

    expect(template).toContain("UTF-8");
    expect(template).toContain("1 MiB");
    expect(template).toContain("1,000");
    expect(template).toContain("<code>expense</code>");
    expect(template).toContain("<code>income</code>");
    expect(template).toContain("<code>transfer</code>");
    expect(template).toMatch(/must identify\s+an account you own/);
    expect(template).toContain("For a transfer, it is the source and must be a bank account");
    expect(template).toContain("required for transfers");
    expect(template).toMatch(/Leave it blank for expenses and\s+income/);
    expect(template).toContain("same currency");
    expect(template).toMatch(/without regard to\s+capitalization/);
    expect(template).toContain("flat JSON object of text keys and text values");
    expect(template).toContain("arrays, nested objects, and non-text values are not accepted");
    expect(template).toContain(
      "type,name,description,category,date,amount,account_id,target_account_id,additional_data",
    );
    expect(template).toContain('method="post"');
    expect(template).toContain('enctype="multipart/form-data"');
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="file"');
    expect(template).toContain('accept=".csv,text/csv"');
    expect(template).toContain('for="{{ form.csv_file.id_for_label }}"');
    expect(template).toContain('id="{{ form.csv_file.auto_id }}_error"');
    expect(template).toContain("confirmation_form.non_field_errors");
  });

  it("renders all-or-nothing errors and confirms only with an opaque preview token", async () => {
    const template = await transactionTemplate("transaction_import_preview.html");

    expect(template).toContain("Nothing was imported");
    expect(template).toContain("CSV line {{ error.source_line }}");
    expect(template).toContain("Importing identical data again creates duplicate transactions");
    expect(template).toContain('aria-label="Normalized transaction import rows"');
    expect(template.match(/scope="col"/g)).toHaveLength(10);
    expect(template).toContain("{% if preview_token and not file_errors and not row_errors %}");
    expect(template).toContain("CSV account ID {{ row.account_id }}");
    expect(template).toContain("CSV account ID {{ row.target_account_id }}");
    expect(template).toContain("{% if row.target_account %}");
    expect(template).toContain("{% url 'transactions:import-confirm' %}");
    expect(template).toContain("{% csrf_token %}");
    expect(template).toContain('type="hidden" name="preview_token" value="{{ preview_token }}"');
    expect(template).not.toContain('type="hidden" name="csv');
    expect(template).not.toContain("<script");
  });
});
