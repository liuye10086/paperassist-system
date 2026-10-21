from typing import Literal
from pydantic import Field,model_validator
from .contracts import Strict


class FigureOriginal(Strict):
    kind:Literal['figure','original','document_version']
    id:str=Field(min_length=1,max_length=100)
    file_id:str=Field(min_length=1,max_length=100)
    image_id:str|None=Field(default=None,min_length=1,max_length=100)

    @model_validator(mode='after')
    def image_binding(self):
        if (self.kind=='document_version')!=(self.image_id is not None): raise ValueError('Document image requires an image identity.')
        if self.kind=='original' and self.id!=self.file_id: raise ValueError('Original source identity must match file.')
        return self


class FigureTexts(Strict):
    title:str=Field(min_length=1,max_length=2000)
    x_label:str=Field(min_length=1,max_length=2000)
    y_label:str=Field(min_length=1,max_length=2000)
    caption:str=Field(min_length=1,max_length=2000)
    series:list[str]=Field(min_length=1,max_length=8)


class FigureTextItem(Strict):
    location:str=Field(min_length=1,max_length=200)
    text:str=Field(min_length=1,max_length=2000)


class FigureLanguageRequest(Strict):
    source:FigureOriginal
    original_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    output_language:Literal['en','zh-CN']
    mode:Literal['local_boxplot','uploaded_replacement','no_text_confirmation']
    reason:str=Field(min_length=1,max_length=3000)
    texts:FigureTexts|None=None
    replacement_file_id:str|None=Field(default=None,min_length=1,max_length=100)
    text_items:list[FigureTextItem]=Field(default_factory=list,max_length=100)
    title:str=Field(default='',max_length=2000)
    caption:str=Field(default='',max_length=6000)

    @model_validator(mode='after')
    def mode_gate(self):
        if not self.reason.strip(): raise ValueError('An explicit modification/inspection reason is required.')
        if self.mode=='local_boxplot':
            if self.source.kind!='figure' or self.texts is None or self.replacement_file_id or self.text_items:
                raise ValueError('Local redraw requires frozen program figure and complete text mapping.')
        elif self.texts is not None: raise ValueError('External image does not accept renderer text mappings.')
        if self.mode=='uploaded_replacement' and (not self.replacement_file_id or not self.text_items):
            raise ValueError('Uploaded replacement needs its file and full visible text inventory.')
        if self.mode=='no_text_confirmation' and (self.replacement_file_id or self.text_items):
            raise ValueError('No-text confirmation uses original pixels and an empty text inventory.')
        if self.mode!='local_boxplot' and self.source.kind=='figure':
            raise ValueError('Program figures must use frozen deterministic redraw.')
        if self.mode!='local_boxplot' and (not self.title.strip() or not self.caption.strip()):
            raise ValueError('External image title and caption are required.')
        if len({t.location for t in self.text_items})!=len(self.text_items): raise ValueError('Duplicate image text location.')
        return self
