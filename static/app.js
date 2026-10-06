const departmentSelect = document.getElementById('department');
const questionInput = document.getElementById('question');
const submitButton = document.getElementById('submit');
const answerElement = document.getElementById('answer');
const citationsElement = document.getElementById('citations');

async function loadDepartments() {
  const response = await fetch('/api/departments');
  const data = await response.json();

  data.departments.forEach((department) => {
    const option = document.createElement('option');
    option.value = department;
    option.textContent = department;
    departmentSelect.appendChild(option);
  });
}

async function askSop() {
  const question = questionInput.value.trim();
  const department = departmentSelect.value;

  if (!question) {
    answerElement.textContent = 'Please enter a question before submitting.';
    citationsElement.innerHTML = '';
    return;
  }

  submitButton.disabled = true;
  answerElement.textContent = 'Checking the approved SOP repository...';
  citationsElement.innerHTML = '';

  const response = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, department: department || null })
  });

  const result = await response.json();
  answerElement.textContent = result.answer || 'No answer retrieved.';

  const citations = result.citations || [];
  if (citations.length === 0) {
    citationsElement.innerHTML = '<div class="empty-state">No approved SOP citations were found.</div>';
    submitButton.disabled = false;
    return;
  }

  citationsElement.innerHTML = citations.map((citation) => `
    <div class="citation">
      <strong>${citation.sop_id} — ${citation.title}</strong>
      <div class="meta">Department: ${citation.department} | Section: ${citation.section} | Version: ${citation.version}</div>
      <div class="meta">Source: ${citation.source} | Effective date: ${citation.effective_date}</div>
    </div>
  `).join('');

  submitButton.disabled = false;
}

submitButton.addEventListener('click', askSop);
questionInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    askSop();
  }
});

loadDepartments();
