frappe.listview_settings["Employee"] = {
	add_fields: ["status", "branch", "department", "designation", "image"],
	filters: [["status", "=", "Active"]],
	get_indicator(doc) {
		return [
			__(doc.status, null, "Employee"),
			{ Active: "green", Inactive: "red", Left: "gray", Suspended: "orange" }[doc.status],
			"status,=," + doc.status,
		];
	},

	onload(listview) {
		listview.get_no_result_message = () => {
			return `
                <div class="msg-box no-border">
                    <div class="mb-4">
                        <svg class="icon icon-xl" style="stroke: var(--text-light);">
                            <use href="#icon-small-file"></use>
                        </svg>
                    </div>
                    <p>${__("No Active Employees Found. Prefer importing if you have many records.")}</p>
                    <p>
						<button class="btn btn-primary btn-sm btn-new-doc">
							${__("Create New")}
						</button>
                        <button class="btn btn-default btn-sm" onclick="frappe.set_route('List', 'Data Import', {reference_doctype: 'Employee'})">
                            ${__("Import Employees")}
                        </button>
                    </p>
                </div>
            `;
		};
	},
};
