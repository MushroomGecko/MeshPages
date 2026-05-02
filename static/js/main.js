function enableButtons() 
{
    document.getElementById("search-button").disabled = false;
    document.getElementById("quick-search-button").disabled = false;
}

function disableButtons() 
{
    document.getElementById("search-button").disabled = true;
    document.getElementById("quick-search-button").disabled = true;
}

function makeDangerous(element)
{
    element.classList.add('text-danger');
    element.classList.remove('text-warning');
    element.classList.remove('text-success');
}

function makeWarning(element)
{
    element.classList.add('text-warning');
    element.classList.remove('text-danger');
    element.classList.remove('text-success');
}

function makeSuccess(element)
{
    element.classList.add('text-success');
    element.classList.remove('text-danger');
    element.classList.remove('text-warning');
}

document.getElementById('text-box').addEventListener('input', function() 
{
    const textValue = this.value;
    const characterCountElement = document.getElementById('character-count-value');
    
    // Find the position of the third slash so we can start character counting after the node ID
    const firstSlash = textValue.indexOf('/');
    const secondSlash = textValue.indexOf('/', firstSlash + 1);
    const thirdSlash = textValue.indexOf('/', secondSlash + 1);

    // Calculate character count
    const characterCount = thirdSlash !== -1 ? textValue.length - thirdSlash : 0;

    // Update character count value
    characterCountElement.textContent = `${characterCount}/200`;

    // Update progress bar
    const progressBar = document.getElementById('character-count-bar');
    const progressPercent = (characterCount / 200) * 100;
    progressBar.style.width = progressPercent + '%';
    
    // Disable buttons if character count is greater than 200
    if (characterCount > 200) 
    {
        disableButtons();
    } 
    else 
    {
        enableButtons();
    }

    // Update colors to match character count
    if (characterCount > 200) 
    {
        makeDangerous(characterCountElement);
        progressBar.className = 'progress-bar bg-danger';
    }
    else if (characterCount > 100)
    {
        makeWarning(characterCountElement);
        progressBar.className = 'progress-bar bg-warning';
    }
    else
    {
        makeSuccess(characterCountElement);
        progressBar.className = 'progress-bar bg-success';
    }
});