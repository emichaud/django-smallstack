# Forms

SmallStack forms use Django's form system with custom CSS classes for consistent styling.

## Text Input

```html
<div class="form-row">
    <div class="form-group">
        <label for="name">Name</label>
        <input type="text" id="name" name="name" class="vTextField"
               placeholder="Enter your name...">
        <span class="helptext">Help text appears below the input</span>
    </div>
</div>
```

The `vTextField` class styles inputs to match the SmallStack theme.

## Two-Column Layout

Use `form-row-2col` for side-by-side fields:

```html
<div class="form-row form-row-2col">
    <div class="form-group">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" class="vTextField">
    </div>
    <div class="form-group">
        <label for="phone">Phone</label>
        <input type="text" id="phone" name="phone" class="vTextField">
    </div>
</div>
```

## Select Dropdown

```html
<select id="role" name="role" class="vTextField">
    <option value="">Choose...</option>
    <option value="admin">Admin</option>
    <option value="user">User</option>
</select>
```

## Textarea

```html
<textarea id="bio" name="bio" class="vLargeTextField"
          rows="4" placeholder="Tell us about yourself..."></textarea>
```

## Date Picker

```html
<div class="date-input-wrapper">
    <input type="date" id="start_date" name="start_date"
           class="vTextField vDateField">
    <button type="button" class="date-picker-btn"
            data-target="start_date" aria-label="Open calendar">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z"/>
        </svg>
    </button>
</div>
```

Use `type="datetime-local"` for combined date and time.

## File Upload

Basic file input:

```html
<input type="file" id="attachment" name="attachment" class="vTextField">
```

## Drag & Drop Upload

```html
<div class="file-upload-wrapper">
    <div class="file-upload-dropzone" id="image-dropzone">
        <svg viewBox="0 0 24 24" width="32" height="32" fill="currentColor"
             style="color: var(--body-quiet-color);">
            <path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/>
        </svg>
        <span class="dropzone-text">Drag & drop an image or click to browse</span>
        <span class="dropzone-filename" id="image-filename"
              style="display: none;"></span>
        <input type="file" id="photo" name="photo" accept="image/*"
               class="file-upload-input">
    </div>
</div>
```

The dropzone JS is included in the starter page's `extra_js` block. Include it if you use drag-and-drop uploads.

## Form Buttons

Place submit and cancel buttons in a `form-row`:

```html
<div class="form-row" style="margin-top: 16px;">
    <button type="button" class="button button-secondary">Cancel</button>
    <button type="submit" class="button button-primary">Save</button>
</div>
```

## Where SmallStack Uses Forms

- **Profile edit** — text fields, image upload, two-column layout
- **Login / Signup** — text inputs with validation
- **Starter page** — full form component demo
