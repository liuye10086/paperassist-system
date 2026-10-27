document.querySelectorAll('[data-width]').forEach(button=>button.addEventListener('click',()=>{
  const width=Number(button.dataset.width);
  document.getElementById('frame-container').style.width=`${width}px`;
  document.getElementById('preview-frame').width=width;
  document.getElementById('preview-frame').height=width===390?844:900;
  document.querySelectorAll('[data-width]').forEach(item=>item.classList.toggle('active',item===button));
}));
