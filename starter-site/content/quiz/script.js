"use strict";

function setup_answers() {
    let answers = document.getElementsByTagName("quiz-a");
    for(let a of answers) {
        a.addEventListener("click", ev => ev.target.classList.add("clicked"));
    }
}

document.addEventListener("DOMContentLoaded", ev => setup_answers());
