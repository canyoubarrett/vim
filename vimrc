
set nocompatible               " be iMproved
filetype off                   " required!

let mapleader = ","

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()
execute pathogen#infect()
autocmd VimEnter * NERDTree
autocmd VimEnter * wincmd p

Bundle 'scrooloose/nerdtree'

colorscheme kolor

set backspace =indent, eol

set history =1000  

set incsearch  

set number

set tabstop =4

set shiftwidth =4

set autoindent

set scrolloff =5 

set encoding =utf-8

set fileencoding =utf-8 



