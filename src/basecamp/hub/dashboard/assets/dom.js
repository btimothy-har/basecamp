export function el(tag, options = {}, ...children) {
	const element = document.createElement(tag);
	if (options.className) element.className = options.className;
	if (options.text !== undefined && options.text !== null) element.textContent = String(options.text);
	for (const [name, value] of Object.entries(options.attrs ?? {})) {
		if (value === undefined || value === null) continue;
		if (name.startsWith("aria-")) {
			element.setAttribute(name, String(value));
		} else if (value !== false) {
			element.setAttribute(name, value === true ? "" : String(value));
		}
	}
	for (const [name, value] of Object.entries(options.data ?? {})) {
		if (value !== undefined && value !== null) element.dataset[name] = String(value);
	}
	for (const [name, value] of Object.entries(options.style ?? {})) {
		element.style.setProperty(name, String(value));
	}
	append(element, children);
	return element;
}

export function append(parent, ...children) {
	for (const child of children.flat(Infinity)) {
		if (child === undefined || child === null || child === false) continue;
		parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
	}
	return parent;
}

export function replace(parent, ...children) {
	parent.replaceChildren();
	append(parent, children);
	return parent;
}

export function option(value, label) {
	return el("option", { attrs: { value }, text: label });
}

export function actionButton(label, action, data = {}, className = "button") {
	return el("button", {
		className,
		text: label,
		attrs: { type: "button" },
		data: { action, ...data },
	});
}
