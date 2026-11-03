function showTab(name) {
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.tabPanel !== name);
  });
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
}

function togglePassword(id, button) {
  const field = document.getElementById(id);
  const hidden = field.getAttribute("type") === "password";
  field.setAttribute("type", hidden ? "text" : "password");
  button.textContent = hidden ? "Hide" : "Show";
}

document.addEventListener("DOMContentLoaded", () => {
  const quiz = document.getElementById("quiz-app");
  if (!quiz) return;

  const raw = document.getElementById("quiz-data");
  const questions = JSON.parse(raw ? raw.textContent : "[]");
  if (!questions.length) return;

  let index = 0;
  let score = 0;
  let answered = false;
  const missed = [];

  const questionEl = document.getElementById("quiz-question");
  const optionsEl = document.getElementById("quiz-options");
  const feedbackEl = document.getElementById("quiz-feedback");
  const scoreEl = document.getElementById("quiz-score");

  function render() {
    answered = false;
    feedbackEl.textContent = "";
    if (index >= questions.length) {
      questionEl.textContent = "Quiz completed!";
      optionsEl.innerHTML = "";
      const percent = questions.length ? ((score / questions.length) * 100).toFixed(1) : 0;
      feedbackEl.textContent = `Final score: ${score} / ${questions.length} (${percent}%).`;
      scoreEl.textContent = "Quiz finished";
      return;
    }
    const current = questions[index];
    questionEl.textContent = current.question;
    scoreEl.textContent = `Question ${index + 1} of ${questions.length}`;
    optionsEl.innerHTML = "";
    current.options.forEach((option, optionIndex) => {
      const label = document.createElement("label");
      label.className = "quiz-option";
      label.innerHTML = `<input type="radio" name="answer" value="${optionIndex}"> ${option}`;
      optionsEl.appendChild(label);
    });
  }

  document.getElementById("check-answer").addEventListener("click", () => {
    if (!questions[index]) return;
    if (answered) {
      feedbackEl.textContent = "Click Next Question to continue.";
      return;
    }
    const selected = optionsEl.querySelector("input:checked");
    if (!selected) {
      feedbackEl.textContent = "Please select an answer first.";
      return;
    }
    const current = questions[index];
    const chosen = current.options[Number(selected.value)];
    answered = true;
    if (chosen.toLowerCase() === current.answer.toLowerCase()) {
      score += 1;
      feedbackEl.innerHTML = `<span class="ok">Correct!</span><br>${current.explanation}`;
    } else {
      missed.push(current);
      feedbackEl.innerHTML = `<span class="bad">Incorrect.</span> Correct answer: ${current.answer}<br>${current.explanation}`;
    }
    scoreEl.textContent = `Score: ${score} / ${questions.length}`;
  });

  document.getElementById("next-question").addEventListener("click", () => {
    if (!answered) {
      feedbackEl.textContent = "Check your answer before continuing.";
      return;
    }
    index += 1;
    render();
  });

  document.getElementById("practice-missed").addEventListener("click", () => {
    if (!missed.length) {
      feedbackEl.textContent = "No missed questions yet. Complete a quiz first.";
      return;
    }
    questions.splice(0, questions.length, ...missed);
    missed.length = 0;
    index = 0;
    score = 0;
    render();
  });

  render();
});
