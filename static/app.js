const loginPanel = document.getElementById('login-panel');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const loginButton = document.getElementById('login-submit');
const passwordChangePanel = document.getElementById('password-change-panel');
const passwordChangeForm = document.getElementById('password-change-form');
const passwordChangeError = document.getElementById('password-change-error');
const passwordChangeButton = document.getElementById('password-change-submit');
const activationPanel = document.getElementById('activation-panel');
const activationForm = document.getElementById('activation-form');
const activationMessage = document.getElementById('activation-message');
const activationSubmit = document.getElementById('activation-submit');
const activationContinue = document.getElementById('activation-continue');
const assistant = document.getElementById('assistant');
const profileName = document.getElementById('profile-name');
const profileDetail = document.getElementById('profile-detail');
const avatar = document.getElementById('avatar');
const logoutButton = document.getElementById('logout');
const departmentSelect = document.getElementById('department');
const queryForm = document.getElementById('query-form');
const questionInput = document.getElementById('question');
const characterCount = document.getElementById('character-count');
const submitButton = document.getElementById('submit');
const answerState = document.getElementById('answer-state');
const answerCard = document.getElementById('answer-card');
const answerElement = document.getElementById('answer');
const answerStatus = document.getElementById('answer-status');
const citationsElement = document.getElementById('citations');
const sourcesEmpty = document.getElementById('sources-empty');
const sourceCount = document.getElementById('source-count');
const adminPanel = document.getElementById('admin-panel');
const createUserForm = document.getElementById('create-user-form');
const adminMessage = document.getElementById('admin-message');
const usersList = document.getElementById('users-list');
const emailSetupWarning = document.getElementById('email-setup-warning');
const bulkUsersForm = document.getElementById('bulk-users-form');
const bulkUsersMessage = document.getElementById('bulk-users-message');
const bulkUsersPreview = document.getElementById('bulk-users-preview');
const bulkPreviewButton = document.getElementById('bulk-preview-submit');
const bulkCreateButton = document.getElementById('bulk-create-valid');
const auditList = document.getElementById('audit-list');
const refreshAuditButton = document.getElementById('refresh-audit');
const sopUploadForm = document.getElementById('sop-upload-form');
const sopUploadButton = document.getElementById('sop-upload-submit');
const sopUploadMessage = document.getElementById('sop-upload-message');
const sopList = document.getElementById('sop-list');
const refreshSopsButton = document.getElementById('refresh-sops');
const librarySearch = document.getElementById('library-search');
const libraryList = document.getElementById('library-list');
const refreshLibraryButton = document.getElementById('refresh-library');

let accessToken = null;
let currentUser = null;
let approvedSops = [];
let bulkPreviewUsers = [];
let activationToken = new URLSearchParams(window.location.hash.slice(1)).get('token');

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new Error('Could not connect. Check your connection and try again.');
  }

  if (response.status === 401 && accessToken) {
    signOut();
    throw new Error('Your session expired. Please sign in again.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('The server returned an unexpected response. Please try again.');
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).filter(Boolean).join(' ')
      : data.detail;
    throw new Error(detail || 'The request could not be completed.');
  }
  return data;
}

function signOut() {
  accessToken = null;
  currentUser = null;
  assistant.classList.add('hidden');
  logoutButton.classList.add('hidden');
  passwordChangePanel.classList.add('hidden');
  activationPanel.classList.add('hidden');
  passwordChangeForm.reset();
  activationForm.reset();
  loginPanel.classList.remove('hidden');
  loginForm.reset();
  loginError.classList.add('hidden');
  document.getElementById('email').focus();
}

function setAnswerStatus(message, state = 'ready') {
  answerStatus.lastChild.textContent = ` ${message}`;
  answerStatus.classList.toggle('is-loading', state === 'loading');
  answerStatus.classList.toggle('is-error', state === 'error');
  answerStatus.classList.toggle('is-warning', state === 'warning');
}

function setAdminMessage(message, isError = false) {
  adminMessage.textContent = message;
  adminMessage.classList.toggle('error', isError);
}

function setSopUploadMessage(message, isError = false) {
  sopUploadMessage.textContent = message;
  sopUploadMessage.classList.toggle('error', isError);
}

async function showSignedIn(user) {
  currentUser = user;
  passwordChangePanel.classList.add('hidden');
  activationPanel.classList.add('hidden');
  loginPanel.classList.add('hidden');
  loginForm.reset();
  loginError.classList.add('hidden');
  assistant.classList.remove('hidden');
  logoutButton.classList.remove('hidden');
  profileName.textContent = user.name;
  profileDetail.textContent = `${user.department} · ${user.role}`;
  avatar.textContent = user.name.trim().charAt(0).toUpperCase() || 'F';
  adminPanel.classList.toggle('hidden', user.role !== 'admin');
  departmentSelect.replaceChildren();
  departmentSelect.disabled = true;

  try {
    const { departments } = await apiFetch('/api/departments');
    if (user.role === 'admin') {
      const allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'All departments';
      departmentSelect.append(allOption);
    }
    departments.forEach((department) => {
      const option = document.createElement('option');
      option.value = department;
      option.textContent = department;
      departmentSelect.append(option);
    });
    if (user.role !== 'admin') departmentSelect.value = user.department;
  } catch (error) {
    setAnswerStatus(error.message, 'error');
  } finally {
    departmentSelect.disabled = false;
  }

  if (user.role === 'admin') {
    loadAuditLogs();
    loadUsers();
    loadSops();
    loadEmailStatus();
  }
  loadApprovedSops();
  questionInput.focus();
}

function showPasswordChange(user) {
  currentUser = null;
  loginPanel.classList.add('hidden');
  assistant.classList.add('hidden');
  passwordChangePanel.classList.remove('hidden');
  logoutButton.classList.remove('hidden');
  passwordChangeForm.reset();
  passwordChangeError.textContent = `Signed in as ${user.email}. Set a new password to continue.`;
  passwordChangeError.classList.remove('error');
  document.getElementById('new-user-password').focus();
}

function showActivationPage() {
  loginPanel.classList.add('hidden');
  activationPanel.classList.remove('hidden');
  if (!activationToken) {
    activationMessage.textContent = 'This activation link is invalid or incomplete. Ask an administrator to resend the invitation.';
    activationMessage.classList.add('error');
    activationSubmit.disabled = true;
    return;
  }
  activationMessage.textContent = 'This secure activation link can be used once and expires after 24 hours.';
  history.replaceState(null, '', window.location.pathname);
  document.getElementById('activation-temporary-password').focus();
}

function showAnswerError(error) {
  answerState.classList.add('hidden');
  answerCard.classList.remove('hidden');
  answerElement.textContent = error.message;
  answerElement.classList.add('error');
  setAnswerStatus('Something went wrong', 'error');
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginButton.disabled = true;
  loginError.classList.add('hidden');
  try {
    const result = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value,
      }),
    });
    accessToken = result.access_token;
    if (result.user.must_change_password) {
      showPasswordChange(result.user);
    } else {
      await showSignedIn(result.user);
    }
  } catch (error) {
    loginError.textContent = error.message;
    loginError.classList.remove('hidden');
  } finally {
    loginButton.disabled = false;
  }
});

passwordChangeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  passwordChangeButton.disabled = true;
  passwordChangeError.textContent = '';
  passwordChangeError.classList.remove('error');
  const newPassword = document.getElementById('new-user-password').value;
  const confirmPassword = document.getElementById('confirm-user-password').value;
  if (newPassword !== confirmPassword) {
    passwordChangeError.textContent = 'The new passwords do not match.';
    passwordChangeError.classList.add('error');
    passwordChangeButton.disabled = false;
    return;
  }
  try {
    const result = await apiFetch('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
    accessToken = result.access_token;
    await showSignedIn(result.user);
  } catch (error) {
    passwordChangeError.textContent = error.message;
    passwordChangeError.classList.add('error');
  } finally {
    passwordChangeButton.disabled = false;
  }
});

activationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  activationSubmit.disabled = true;
  activationMessage.textContent = '';
  activationMessage.classList.remove('error');
  const temporaryPassword = document.getElementById('activation-temporary-password').value;
  const newPassword = document.getElementById('activation-new-password').value;
  const confirmPassword = document.getElementById('activation-confirm-password').value;
  if (newPassword !== confirmPassword) {
    activationMessage.textContent = 'The new passwords do not match.';
    activationMessage.classList.add('error');
    activationSubmit.disabled = false;
    return;
  }
  if (newPassword === temporaryPassword) {
    activationMessage.textContent = 'Choose a new password that differs from the temporary password.';
    activationMessage.classList.add('error');
    activationSubmit.disabled = false;
    return;
  }
  try {
    const result = await apiFetch('/api/auth/activate', {
      method: 'POST',
      body: JSON.stringify({
        token: activationToken,
        temporary_password: temporaryPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
    activationToken = null;
    activationForm.reset();
    activationSubmit.classList.add('hidden');
    activationMessage.textContent = `Account activated for ${result.email}. You can now sign in with your new password.`;
    activationContinue.classList.remove('hidden');
  } catch (error) {
    activationMessage.textContent = error.message;
    activationMessage.classList.add('error');
  } finally {
    activationSubmit.disabled = false;
  }
});

activationContinue.addEventListener('click', () => {
  activationPanel.classList.add('hidden');
  loginPanel.classList.remove('hidden');
  document.getElementById('email').value = '';
  document.getElementById('password').value = '';
  document.getElementById('email').focus();
});

logoutButton.addEventListener('click', signOut);

async function askSop(event) {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) {
    questionInput.focus();
    questionInput.setCustomValidity('Enter a question to search the SOP library.');
    questionInput.reportValidity();
    return;
  }
  questionInput.setCustomValidity('');

  submitButton.disabled = true;
  queryForm.setAttribute('aria-busy', 'true');
  answerCard.classList.add('hidden');
  answerElement.classList.remove('error');
  answerState.classList.remove('hidden');
  answerState.classList.add('is-searching');
  answerState.querySelector('h2').textContent = 'Looking through approved SOPs…';
  answerState.querySelector('p').textContent = 'Finding the most relevant guidance for your question.';
  setAnswerStatus('Searching approved SOPs', 'loading');
  citationsElement.replaceChildren();
  sourcesEmpty.textContent = 'Searching the approved library…';
  citationsElement.append(sourcesEmpty);
  sourceCount.textContent = '';

  try {
    const result = await apiFetch('/api/query', {
      method: 'POST',
      body: JSON.stringify({
        question,
        department: departmentSelect.value || null,
      }),
    });
    answerState.classList.add('hidden');
    answerState.classList.remove('is-searching');
    answerCard.classList.remove('hidden');
    answerElement.textContent = result.answer || 'No answer was returned.';
    answerElement.classList.remove('error');
    setAnswerStatus(
      result.missing_sop ? 'No approved match found' : 'Grounded in approved SOPs',
      result.missing_sop ? 'warning' : 'ready',
    );
    renderCitations(result.citations || []);
  } catch (error) {
    answerState.classList.remove('is-searching');
    showAnswerError(error);
    citationsElement.replaceChildren();
    sourcesEmpty.textContent = 'Sources are unavailable until the request succeeds.';
    citationsElement.append(sourcesEmpty);
  } finally {
    submitButton.disabled = false;
    queryForm.removeAttribute('aria-busy');
  }
}

function renderCitations(citations) {
  citationsElement.replaceChildren();
  sourceCount.textContent = citations.length ? `(${citations.length})` : '';
  if (!citations.length) {
    sourcesEmpty.textContent = 'No approved SOP citations matched this question.';
    citationsElement.append(sourcesEmpty);
    return;
  }

  citations.forEach((citation) => {
    const card = document.createElement('article');
    card.className = 'citation-card';
    const icon = document.createElement('span');
    icon.className = 'source-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '▤';
    const content = document.createElement('div');
    const title = document.createElement('strong');
    title.className = 'citation-title';
    title.textContent = `${citation.sop_id} — ${citation.title}`;
    const metadata = document.createElement('div');
    metadata.className = 'citation-meta';
    [
      citation.department,
      citation.section,
      `Version ${citation.version}`,
      `Effective ${citation.effective_date}`,
    ].forEach((value) => {
      if (!value) return;
      const item = document.createElement('span');
      item.textContent = value;
      metadata.append(item);
    });
    const source = document.createElement('p');
    source.className = 'citation-source';
    source.textContent = `Source: ${citation.source}`;
    content.append(title, metadata, source);
    card.append(icon, content);
    citationsElement.append(card);
  });
}

queryForm.addEventListener('submit', askSop);
questionInput.addEventListener('input', () => {
  characterCount.textContent = `${questionInput.value.length} / 2000`;
  questionInput.setCustomValidity('');
});
document.querySelectorAll('.suggestion').forEach((button) => {
  button.addEventListener('click', () => {
    questionInput.value = button.dataset.question || '';
    characterCount.textContent = `${questionInput.value.length} / 2000`;
    questionInput.focus();
  });
});

createUserForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = createUserForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  setAdminMessage('');
  try {
    const result = await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        name: document.getElementById('new-name').value,
        email: document.getElementById('new-email').value,
        department: document.getElementById('new-department').value,
        role: document.getElementById('new-role').value,
      }),
    });
    setAdminMessage(`Account created for ${result.email}; activation email sent.`);
    createUserForm.reset();
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    await loadUsers();
  } finally {
    submit.disabled = false;
  }
});

async function loadEmailStatus() {
  try {
    const { configured } = await apiFetch('/api/admin/email-status');
    emailSetupWarning.classList.toggle('hidden', configured);
    emailSetupWarning.textContent = configured
      ? ''
      : 'Email delivery is not configured. Set the SMTP environment variables before creating or inviting accounts.';
    emailSetupWarning.classList.toggle('error', !configured);
  } catch (error) {
    emailSetupWarning.textContent = error.message;
    emailSetupWarning.classList.remove('hidden');
    emailSetupWarning.classList.add('error');
  }
}

bulkUsersForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = document.getElementById('bulk-users-file').files[0];
  if (!file) return;
  bulkPreviewButton.disabled = true;
  bulkUsersMessage.textContent = 'Reading and validating spreadsheet…';
  bulkUsersMessage.classList.remove('error');
  bulkUsersPreview.classList.add('hidden');
  bulkCreateButton.classList.add('hidden');
  bulkPreviewUsers = [];
  try {
    const formData = new FormData();
    formData.append('file', file);
    const result = await apiFetch('/api/admin/users/preview', {
      method: 'POST',
      body: formData,
    });
    bulkPreviewUsers = result.users;
    renderBulkUsersPreview(result.users);
    bulkUsersMessage.textContent = `${result.valid_count} valid of ${result.users.length} spreadsheet rows. Review the list before creating accounts.`;
    bulkCreateButton.disabled = result.valid_count === 0;
    bulkCreateButton.classList.toggle('hidden', result.valid_count === 0);
  } catch (error) {
    bulkUsersMessage.textContent = error.message;
    bulkUsersMessage.classList.add('error');
  } finally {
    bulkPreviewButton.disabled = false;
  }
});

function renderBulkUsersPreview(users) {
  bulkUsersPreview.replaceChildren();
  const table = document.createElement('table');
  table.className = 'bulk-users-table';
  const header = document.createElement('tr');
  ['Row', 'Name', 'Email', 'Department', 'Role', 'Validation'].forEach((label) => {
    const cell = document.createElement('th');
    cell.scope = 'col';
    cell.textContent = label;
    header.append(cell);
  });
  const head = document.createElement('thead');
  head.append(header);
  const body = document.createElement('tbody');
  users.forEach((user) => {
    const row = document.createElement('tr');
    [user.row, user.name, user.email, user.department, user.role].forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value ?? '';
      row.append(cell);
    });
    const validation = document.createElement('td');
    validation.className = user.valid ? 'bulk-valid' : 'bulk-invalid';
    validation.textContent = user.valid ? 'Ready to create' : user.errors.join(' ');
    row.append(validation);
    body.append(row);
  });
  table.append(head, body);
  bulkUsersPreview.append(table);
  bulkUsersPreview.classList.remove('hidden');
}

bulkCreateButton.addEventListener('click', async () => {
  const validUsers = bulkPreviewUsers
    .filter((user) => user.valid)
    .map(({ name, email, department, role }) => ({ name, email, department, role }));
  if (!validUsers.length) return;
  bulkCreateButton.disabled = true;
  bulkUsersMessage.textContent = 'Creating accounts and sending invitations…';
  bulkUsersMessage.classList.remove('error');
  try {
    const result = await apiFetch('/api/admin/users/bulk', {
      method: 'POST',
      body: JSON.stringify({ users: validUsers }),
    });
    bulkUsersMessage.textContent =
      `${result.created_count} accounts created and invited; ${result.failed_count} failed.`;
    renderBulkCreateResults(result.results);
    bulkCreateButton.classList.add('hidden');
    bulkPreviewUsers = [];
    await loadUsers();
  } catch (error) {
    bulkUsersMessage.textContent = error.message;
    bulkUsersMessage.classList.add('error');
    bulkCreateButton.disabled = false;
  }
});

function renderBulkCreateResults(results) {
  const list = document.createElement('ul');
  list.className = 'bulk-create-results';
  results.forEach((result) => {
    const item = document.createElement('li');
    item.className = result.status === 'created' ? 'bulk-valid' : 'bulk-invalid';
    item.textContent = result.status === 'created'
      ? `${result.email}: invitation sent.`
      : `${result.email}: ${result.message}`;
    list.append(item);
  });
  bulkUsersPreview.replaceChildren(list);
  bulkUsersPreview.classList.remove('hidden');
}

async function loadUsers() {
  usersList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading team accounts…';
  usersList.append(loading);
  try {
    const { users } = await apiFetch('/api/admin/users');
    usersList.replaceChildren();
    if (!users.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No team accounts found.';
      usersList.append(empty);
      return;
    }
    users.forEach((user) => {
      const row = document.createElement('article');
      row.className = 'user-row';
      const info = document.createElement('div');
      info.className = 'user-info';
      const name = document.createElement('strong');
      name.textContent = user.name;
      const detail = document.createElement('span');
      detail.textContent = `${user.email} · ${user.department} · ${user.role}`;
      info.append(name, detail);

      const active = document.createElement('span');
      active.className = `user-state${user.is_active ? '' : ' inactive'}`;
      active.textContent = user.is_active ? 'Active' : 'Inactive';
      const state = document.createElement('div');
      state.className = 'user-status';
      state.append(active);
      if (user.activation_pending) {
        const pending = document.createElement('span');
        pending.className = 'password-required';
        pending.textContent = 'Pending activation';
        state.append(pending);
      } else if (user.must_change_password) {
        const pending = document.createElement('span');
        pending.className = 'password-required';
        pending.textContent = 'Password change required';
        state.append(pending);
      }
      row.append(info, state);

      if (user.id !== currentUser.id) {
        const actions = document.createElement('div');
        actions.className = 'user-actions';
        if (user.activation_pending) {
          const resend = document.createElement('button');
          resend.className = 'user-toggle';
          resend.type = 'button';
          resend.textContent = 'Resend invitation';
          resend.addEventListener('click', () => resendActivation(user, resend));
          actions.append(resend);
        } else {
          if (user.is_active) {
            const reset = document.createElement('button');
            reset.className = 'user-toggle';
            reset.type = 'button';
            reset.textContent = 'Reset password';
            reset.setAttribute('aria-label', `Reset password for ${user.name}`);
            reset.setAttribute('aria-expanded', 'false');
            reset.addEventListener('click', () => openPasswordResetForm(user, row, reset));
            actions.append(reset);
          }
          const toggle = document.createElement('button');
          toggle.className = 'user-toggle';
          toggle.type = 'button';
          toggle.textContent = user.is_active ? 'Deactivate' : 'Activate';
          toggle.setAttribute(
            'aria-label',
            `${user.is_active ? 'Deactivate' : 'Activate'} ${user.name}`,
          );
          toggle.addEventListener('click', () => setUserActive(user, toggle));
          actions.append(toggle);
        }

        const remove = document.createElement('button');
        remove.className = 'user-toggle user-delete';
        remove.type = 'button';
        remove.textContent = 'Delete';
        remove.setAttribute('aria-label', `Permanently delete ${user.name}`);
        remove.addEventListener('click', () => deleteUserAccount(user, remove));
        actions.append(remove);
        row.append(actions);
      }
      usersList.append(row);
    });
  } catch (error) {
    usersList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    usersList.append(message);
  }
}

async function resendActivation(user, button) {
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}/activation`, {
      method: 'POST',
    });
    setAdminMessage(`A new activation email was sent to ${user.email}.`);
  } catch (error) {
    setAdminMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteUserAccount(user, button) {
  const confirmed = window.confirm(
    `Permanently delete ${user.name} (${user.email})? This cannot be undone. Historical audit and SOP-review records will be retained.`,
  );
  if (!confirmed) return;
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}`, {
      method: 'DELETE',
    });
    setAdminMessage(`Account ${user.email} was permanently deleted.`);
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    button.disabled = false;
  }
}

function openPasswordResetForm(user, row, resetButton) {
  const existingForm = document.querySelector('.user-reset-form');
  if (existingForm) {
    const existingButton = existingForm.previousElementSibling
      ?.querySelector('[aria-expanded="true"]');
    existingForm.remove();
    existingButton?.setAttribute('aria-expanded', 'false');
    if (existingForm.dataset.userId === user.id) {
      resetButton.focus();
      return;
    }
  }

  const form = document.createElement('form');
  form.className = 'user-reset-form';
  form.setAttribute('aria-label', `Set temporary password for ${user.name}`);
  form.dataset.userId = user.id;

  const submit = document.createElement('button');
  submit.className = 'button button-primary';
  submit.type = 'submit';
  submit.textContent = 'Generate temporary password';
  const cancel = document.createElement('button');
  cancel.className = 'button button-quiet';
  cancel.type = 'button';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', () => {
    form.remove();
    resetButton.setAttribute('aria-expanded', 'false');
    resetButton.focus();
  });
  const hint = document.createElement('p');
  hint.className = 'user-reset-hint';
  hint.textContent = 'A secure password will be generated and shown once. Share it securely with the team member.';
  form.append(hint, submit, cancel);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      const result = await apiFetch(
        `/api/admin/users/${encodeURIComponent(user.id)}/password-reset`,
        { method: 'POST' },
      );
      showGeneratedTemporaryPassword(
        form,
        user,
        resetButton,
        result.temporary_password,
      );
      const status = row.querySelector('.user-status');
      if (status && !status.querySelector('.password-required')) {
        const pending = document.createElement('span');
        pending.className = 'password-required';
        pending.textContent = 'Password change required';
        status.append(pending);
      }
      setAdminMessage(
        `A temporary password was generated for ${user.email}. It will not be shown again after this panel is closed.`,
      );
    } catch (error) {
      setAdminMessage(error.message, true);
      submit.disabled = false;
    }
  });

  row.after(form);
  submit.focus();
  resetButton.setAttribute('aria-expanded', 'true');
}

function showGeneratedTemporaryPassword(form, user, resetButton, password) {
  const heading = document.createElement('strong');
  heading.textContent = `Temporary password for ${user.email}`;
  const guidance = document.createElement('p');
  guidance.className = 'user-reset-hint';
  guidance.textContent = 'Copy it now and share it securely. The team member must change it when they sign in.';
  const passwordField = document.createElement('input');
  passwordField.type = 'text';
  passwordField.value = password;
  passwordField.readOnly = true;
  passwordField.autocomplete = 'off';
  passwordField.spellcheck = false;
  passwordField.setAttribute('aria-label', 'Generated temporary password');

  const actions = document.createElement('div');
  actions.className = 'user-reset-result-actions';
  const copy = document.createElement('button');
  copy.className = 'button button-primary';
  copy.type = 'button';
  copy.textContent = 'Copy password';
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(password);
      copy.textContent = 'Copied';
    } catch {
      passwordField.focus();
      passwordField.select();
      copy.textContent = 'Select and copy';
    }
  });
  const close = document.createElement('button');
  close.className = 'button button-quiet';
  close.type = 'button';
  close.textContent = 'Done';
  close.addEventListener('click', () => {
    form.remove();
    resetButton.setAttribute('aria-expanded', 'false');
    resetButton.focus();
  });
  actions.append(copy, close);
  form.replaceChildren(heading, guidance, passwordField, actions);
  copy.focus();
}

async function setUserActive(user, button) {
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}/active`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: !user.is_active }),
    });
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    button.disabled = false;
  }
}

async function loadAuditLogs() {
  refreshAuditButton.disabled = true;
  auditList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading audit activity…';
  auditList.append(loading);
  try {
    const { audit_logs: logs } = await apiFetch('/api/admin/audit-logs?limit=25');
    auditList.replaceChildren();
    if (!logs.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No queries have been recorded yet.';
      auditList.append(empty);
      return;
    }
    logs.forEach((log) => {
      const item = document.createElement('article');
      item.className = 'audit-entry';
      const heading = document.createElement('strong');
      heading.textContent = `${log.email} · ${log.department}`;
      const question = document.createElement('p');
      question.textContent = log.question;
      const result = document.createElement('p');
      result.className = 'meta';
      const outcome = log.missing_sop
        ? 'No approved match'
        : log.success
          ? `SOPs: ${log.retrieved_sops.join(', ')}`
          : 'Access denied';
      result.textContent = `${log.created_at} · ${outcome}`;
      item.append(heading, question, result);
      auditList.append(item);
    });
  } catch (error) {
    auditList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    auditList.append(message);
  } finally {
    refreshAuditButton.disabled = false;
  }
}

refreshAuditButton.addEventListener('click', loadAuditLogs);

sopUploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  sopUploadButton.disabled = true;
  setSopUploadMessage('Uploading and extracting the document…');
  try {
    const result = await apiFetch('/api/admin/sops/upload', {
      method: 'POST',
      body: new FormData(sopUploadForm),
    });
    setSopUploadMessage(`Uploaded ${result.sop_id || 'SOP'} for review.`);
    sopUploadForm.reset();
    await loadSops();
  } catch (error) {
    setSopUploadMessage(error.message, true);
  } finally {
    sopUploadButton.disabled = false;
  }
});

async function loadSops() {
  refreshSopsButton.disabled = true;
  sopList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading SOP versions…';
  sopList.append(loading);
  try {
    const { sops } = await apiFetch('/api/admin/sops');
    sopList.replaceChildren();
    if (!sops.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No uploaded SOP versions yet.';
      sopList.append(empty);
      return;
    }
    sops.forEach((sop) => {
      const row = document.createElement('article');
      row.className = 'sop-row';
      const info = document.createElement('div');
      info.className = 'sop-info';
      const title = document.createElement('strong');
      title.textContent = `${sop.sop_id} · ${sop.title}`;
      const detail = document.createElement('span');
      detail.textContent = `${sop.department} · v${sop.version} · ${sop.section_count} sections · Effective ${sop.effective_date}`;
      const status = document.createElement('span');
      status.className = `sop-status status-${sop.status}`;
      status.textContent = sop.status.replaceAll('_', ' ');
      info.append(title, detail, status);
      row.append(info);
      const preview = document.createElement('div');
      preview.className = 'sop-preview hidden';
      const previewButton = document.createElement('button');
      previewButton.type = 'button';
      previewButton.className = 'user-toggle';
      previewButton.textContent = 'Preview sections';
      previewButton.setAttribute('aria-expanded', 'false');
      previewButton.addEventListener('click', async () => {
        if (!preview.classList.contains('hidden')) {
          preview.classList.add('hidden');
          previewButton.setAttribute('aria-expanded', 'false');
          previewButton.textContent = 'Preview sections';
          return;
        }
        previewButton.disabled = true;
        try {
          const result = await apiFetch(
            `/api/admin/sops/${encodeURIComponent(sop.id)}`,
          );
          preview.replaceChildren();
          result.sections.forEach((section) => {
            const sectionCard = document.createElement('section');
            sectionCard.className = 'sop-preview-section';
            const heading = document.createElement('h4');
            heading.textContent = section.heading;
            const content = document.createElement('p');
            content.textContent = section.content;
            sectionCard.append(heading, content);
            preview.append(sectionCard);
          });
          preview.classList.remove('hidden');
          previewButton.setAttribute('aria-expanded', 'true');
          previewButton.textContent = 'Hide sections';
        } catch (error) {
          setSopUploadMessage(error.message, true);
        } finally {
          previewButton.disabled = false;
        }
      });
      row.append(previewButton, preview);
      if (sop.status === 'pending_review') {
        const actions = document.createElement('div');
        actions.className = 'sop-actions';
        [
          ['approve', 'Approve', 'button-primary'],
          ['reject', 'Reject', 'button-quiet'],
        ].forEach(([action, label, style]) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = `button ${style}`;
          button.textContent = label;
          button.addEventListener('click', () => reviewSop(sop, action, button));
          actions.append(button);
        });
        row.append(actions);
      }
      sopList.append(row);
    });
  } catch (error) {
    sopList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    sopList.append(message);
  } finally {
    refreshSopsButton.disabled = false;
  }
}

async function reviewSop(sop, action, button) {
  button.disabled = true;
  const reviewNote = window.prompt(`Optional review note for ${action}:`);
  if (reviewNote === null) {
    button.disabled = false;
    return;
  }
  const body = new FormData();
  body.set('action', action);
  body.set('review_note', reviewNote);
  try {
    await apiFetch(`/api/admin/sops/${encodeURIComponent(sop.id)}/review`, {
      method: 'POST',
      body,
    });
    const result = action === 'approve' ? 'approved' : 'rejected';
    setSopUploadMessage(`${sop.sop_id} ${result} successfully.`);
    await loadSops();
  } catch (error) {
    setSopUploadMessage(error.message, true);
    button.disabled = false;
  }
}

refreshSopsButton.addEventListener('click', loadSops);

async function loadApprovedSops() {
  libraryList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading approved procedures…';
  libraryList.append(loading);
  refreshLibraryButton.disabled = true;
  try {
    const result = await apiFetch('/api/sops');
    approvedSops = result.sops;
    renderApprovedSops();
  } catch (error) {
    libraryList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    libraryList.append(message);
  } finally {
    refreshLibraryButton.disabled = false;
  }
}

function renderApprovedSops() {
  const query = librarySearch.value.trim().toLocaleLowerCase();
  const visible = approvedSops.filter((sop) => (
    `${sop.sop_id} ${sop.title} ${sop.department} ${sop.version}`
      .toLocaleLowerCase()
      .includes(query)
  ));
  libraryList.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement('p');
    empty.className = 'sources-empty';
    empty.textContent = query
      ? 'No approved procedures match this search.'
      : 'No effective approved SOPs are available to your account.';
    libraryList.append(empty);
    return;
  }

  visible.forEach((sop) => {
    const item = document.createElement('article');
    item.className = 'library-item';
    const identity = document.createElement('div');
    identity.className = 'library-identity';
    const title = document.createElement('strong');
    title.textContent = sop.title;
    const sopId = document.createElement('span');
    sopId.textContent = sop.sop_id;
    identity.append(title, sopId);
    const metadata = document.createElement('div');
    metadata.className = 'library-metadata';
    [sop.department, `Version ${sop.version}`, `Effective ${sop.effective_date}`]
      .forEach((value) => {
        const tag = document.createElement('span');
        tag.textContent = value;
        metadata.append(tag);
      });
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'button button-quiet library-ask';
    button.textContent = 'Ask about this';
    button.addEventListener('click', () => {
      if (currentUser.role === 'admin') departmentSelect.value = sop.department;
      questionInput.value = `What does ${sop.sop_id} say about this procedure?`;
      characterCount.textContent = `${questionInput.value.length} / 2000`;
      questionInput.focus();
      questionInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    item.append(identity, metadata, button);
    libraryList.append(item);
  });
}

librarySearch.addEventListener('input', renderApprovedSops);
refreshLibraryButton.addEventListener('click', loadApprovedSops);

if (window.location.pathname === '/activate') {
  showActivationPage();
}
